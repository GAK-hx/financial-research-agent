import unittest
from datetime import date
from unittest.mock import patch

import httpx

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import Intent, QuerySpec
from financial_research_agent.providers.model import (
    OpenAICompatibleProvider,
    ProviderUnavailable,
)


class FakeResponse:
    def __init__(
        self,
        content: str,
        *,
        usage: dict | None = None,
        request_id: str | None = None,
    ) -> None:
        self.content = content
        self.usage = usage
        self.request_id = request_id

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "id": self.request_id,
            "choices": [{"message": {"content": self.content}}],
            "usage": self.usage,
        }


class FakeClient:
    def __init__(
        self,
        content: str,
        *,
        usage: dict | None = None,
        request_id: str | None = None,
    ) -> None:
        self.response = FakeResponse(
            content, usage=usage, request_id=request_id
        )
        self.payload: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def post(self, url: str, headers: dict, json: dict) -> FakeResponse:
        self.payload = json
        return self.response


class FlakyClient(FakeClient):
    def __init__(self, content: str, failures: int) -> None:
        super().__init__(content)
        self.failures = failures
        self.calls = 0

    async def post(self, url: str, headers: dict, json: dict) -> FakeResponse:
        self.calls += 1
        if self.calls <= self.failures:
            request = httpx.Request("POST", url)
            raise httpx.ConnectError("temporary network failure", request=request)
        return await super().post(url, headers, json)


class ProtocolFlakyClient(FakeClient):
    def __init__(self, content: str, failures: int) -> None:
        super().__init__(content)
        self.failures = failures
        self.calls = 0

    async def post(self, url: str, headers: dict, json: dict) -> FakeResponse:
        self.calls += 1
        if self.calls <= self.failures:
            request = httpx.Request("POST", url)
            raise httpx.RemoteProtocolError(
                "peer closed connection", request=request
            )
        return await super().post(url, headers, json)


class RateLimitedResponse:
    def __init__(self, url: str) -> None:
        self.request = httpx.Request("POST", url)
        self.response = httpx.Response(
            429, request=self.request, json={"error": "rate limited"}
        )

    def raise_for_status(self) -> None:
        raise httpx.HTTPStatusError(
            "rate limited",
            request=self.request,
            response=self.response,
        )


class RateLimitedClient(FakeClient):
    def __init__(self, content: str, failures: int) -> None:
        super().__init__(content)
        self.failures = failures
        self.calls = 0

    async def post(self, url: str, headers: dict, json: dict):
        self.calls += 1
        if self.calls <= self.failures:
            return RateLimitedResponse(url)
        return await super().post(url, headers, json)


class UnexpectedFailureClient(FakeClient):
    async def post(self, url: str, headers: dict, json: dict) -> FakeResponse:
        raise RuntimeError("unexpected client failure")


class RecordingAttemptObserver:
    def __init__(self) -> None:
        self.closed: list[tuple[object, bool]] = []

    async def before_attempt(self, attempt: int) -> object:
        return f"attempt-{attempt}"

    async def after_attempt(self, token: object, *, succeeded: bool) -> None:
        self.closed.append((token, succeeded))


class ModelProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            model_name="deepseek-v4-flash",
            model_api_key="test-key",
            model_base_url="https://api.deepseek.com",
        )
        self.query = QuerySpec(
            stock_codes=["600519"],
            start_date=date(2026, 6, 15),
            end_date=date(2026, 7, 15),
            intent=Intent.MARKET,
            dimensions=["trend"],
        )

    async def test_plan_payload_contains_schema_and_flash_json_controls(self):
        client = FakeClient(
            '{"query":{"stock_codes":["600519"],"start_date":"2026-06-15",'
            '"end_date":"2026-07-15","intent":"market","dimensions":["trend"]},'
            '"tasks":[{"task_id":"market","tool_name":"market_query",'
            '"arguments":{"stock_code":"600519"},"depends_on":[]}],'
            '"expected_sections":["market"]}'
        )
        with patch(
            "financial_research_agent.providers.model.httpx.AsyncClient",
            return_value=client,
        ):
            result = await OpenAICompatibleProvider(self.settings).create_plan(
                "分析贵州茅台走势",
                self.query,
                [{"name": "market_query", "input_schema": {"type": "object"}}],
            )
        self.assertEqual(result["tasks"][0]["tool_name"], "market_query")
        self.assertIsNotNone(client.payload)
        assert client.payload is not None
        self.assertEqual(client.payload["thinking"], {"type": "disabled"})
        self.assertEqual(client.payload["max_tokens"], 4096)
        prompt = client.payload["messages"][0]["content"]
        self.assertIn('"output_schema"', prompt)
        self.assertIn('"tasks"', prompt)

    async def test_report_payload_contains_schema(self):
        client = FakeClient(
            '{"subjects":["600519"],"summary":"基于证据的摘要",'
            '"summary_evidence_ids":["run:evidence"],'
            '"claims":[{"claim":"趋势存在不确定性",'
            '"evidence_ids":["run:evidence"],"confidence":"medium"}],'
            '"risks":[{"risk":"样本有限","classification":"model_interpretation",'
            '"evidence_ids":["run:evidence"],"confidence":"medium"}],'
            '"limitations":[],"data_as_of":null,'
            '"disclaimer":"仅供研究参考，不构成投资建议。"}'
        )
        context = {
            "query": self.query.model_dump(mode="json"),
            "evidence": [{"evidence_id": "run:evidence"}],
        }
        with patch(
            "financial_research_agent.providers.model.httpx.AsyncClient",
            return_value=client,
        ):
            result = await OpenAICompatibleProvider(self.settings).create_report(
                "分析贵州茅台走势", context
            )
        self.assertEqual(result["subjects"], ["600519"])
        assert client.payload is not None
        self.assertEqual(client.payload["max_tokens"], 8192)
        prompt = client.payload["messages"][0]["content"]
        self.assertIn('"output_schema"', prompt)
        self.assertIn("exact institution", prompt)
        self.assertIn("one evidence chunk only", prompt)

    async def test_empty_json_content_is_explicit_failure(self):
        client = FakeClient("   ")
        with patch(
            "financial_research_agent.providers.model.httpx.AsyncClient",
            return_value=client,
        ):
            with self.assertRaisesRegex(ProviderUnavailable, "empty content"):
                await OpenAICompatibleProvider(self.settings).create_plan(
                    "分析贵州茅台走势", self.query, []
                )

    async def test_transient_network_error_retries_then_succeeds(self):
        client = FlakyClient(
            '{"query":{"stock_codes":["600519"],"start_date":"2026-06-15",'
            '"end_date":"2026-07-15","intent":"market","dimensions":["trend"]},'
            '"tasks":[{"task_id":"market","tool_name":"market_query",'
            '"arguments":{"stock_code":"600519"},"depends_on":[]}],'
            '"expected_sections":["market"]}',
            failures=2,
        )
        settings = self.settings.model_copy(
            update={"model_max_retries": 2, "model_retry_backoff_seconds": 0}
        )
        with patch(
            "financial_research_agent.providers.model.httpx.AsyncClient",
            return_value=client,
        ):
            result = await OpenAICompatibleProvider(settings).create_plan(
                "分析贵州茅台走势",
                self.query,
                [{"name": "market_query", "input_schema": {"type": "object"}}],
            )
        self.assertEqual(client.calls, 3)
        self.assertEqual(result["tasks"][0]["tool_name"], "market_query")

    async def test_rate_limit_retries_then_succeeds(self):
        client = RateLimitedClient('{"ok":true}', failures=2)
        settings = self.settings.model_copy(
            update={"model_max_retries": 2, "model_retry_backoff_seconds": 0}
        )
        with patch(
            "financial_research_agent.providers.model.httpx.AsyncClient",
            return_value=client,
        ):
            response = await OpenAICompatibleProvider(
                settings
            ).create_plan_response("测试", self.query, [])
        self.assertEqual(client.calls, 3)
        self.assertEqual(response.content, {"ok": True})

    async def test_remote_protocol_error_retries_then_succeeds(self):
        client = ProtocolFlakyClient('{"ok":true}', failures=1)
        settings = self.settings.model_copy(
            update={"model_max_retries": 1, "model_retry_backoff_seconds": 0}
        )
        with patch(
            "financial_research_agent.providers.model.httpx.AsyncClient",
            return_value=client,
        ):
            response = await OpenAICompatibleProvider(
                settings
            ).create_plan_response("测试", self.query, [])
        self.assertEqual(client.calls, 2)
        self.assertEqual(response.content, {"ok": True})

    async def test_unexpected_client_error_closes_attempt_reservation(self):
        client = UnexpectedFailureClient('{"ok":true}')
        observer = RecordingAttemptObserver()
        with patch(
            "financial_research_agent.providers.model.httpx.AsyncClient",
            return_value=client,
        ):
            with self.assertRaisesRegex(
                RuntimeError, "unexpected client failure"
            ):
                await OpenAICompatibleProvider(
                    self.settings
                ).create_plan_response(
                    "测试",
                    self.query,
                    [],
                    attempt_observer=observer,
                )
        self.assertEqual(observer.closed, [("attempt-0", False)])

    async def test_v4_pro_usage_and_cache_tokens_are_recorded(self):
        client = FakeClient(
            '{"ok":true}',
            usage={
                "prompt_tokens": 2000,
                "completion_tokens": 200,
                "total_tokens": 2200,
                "prompt_cache_hit_tokens": 1000,
                "prompt_cache_miss_tokens": 1000,
            },
            request_id="deepseek-request-1",
        )
        settings = self.settings.model_copy(
            update={
                "model_name": "deepseek-v4-pro",
                "model_context_window_tokens": 1_000_000,
                "model_input_price_cny_per_million": 3,
                "model_cache_hit_price_cny_per_million": 0.025,
                "model_output_price_cny_per_million": 6,
            }
        )
        with patch(
            "financial_research_agent.providers.model.httpx.AsyncClient",
            return_value=client,
        ):
            response = await OpenAICompatibleProvider(
                settings
            ).create_plan_response("测试", self.query, [])
        self.assertEqual(response.provider_request_id, "deepseek-request-1")
        self.assertEqual(response.usage.input_tokens, 2000)
        self.assertEqual(response.usage.cache_hit_tokens, 1000)
        self.assertEqual(response.usage.cache_miss_tokens, 1000)
        self.assertEqual(response.usage.cost_microunits, 4225)
        self.assertEqual(
            OpenAICompatibleProvider(settings).capability.context_window_tokens,
            1_000_000,
        )

    async def test_thinking_mode_uses_official_controls(self):
        client = FakeClient('{"ok":true}')
        settings = self.settings.model_copy(
            update={
                "model_name": "deepseek-v4-pro",
                "model_thinking_mode": "enabled",
                "model_reasoning_effort": "max",
            }
        )
        with patch(
            "financial_research_agent.providers.model.httpx.AsyncClient",
            return_value=client,
        ):
            await OpenAICompatibleProvider(settings).create_plan_response(
                "测试", self.query, []
            )
        assert client.payload is not None
        self.assertEqual(client.payload["thinking"], {"type": "enabled"})
        self.assertEqual(client.payload["reasoning_effort"], "max")
        self.assertNotIn("temperature", client.payload)


if __name__ == "__main__":
    unittest.main()
