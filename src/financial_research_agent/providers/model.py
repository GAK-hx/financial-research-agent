from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Protocol

import httpx
from pydantic import BaseModel

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import AnalysisPlan, QuerySpec, ResearchReport
from financial_research_agent.governance.models import (
    ModelGatewayResponse,
    ModelUsage,
    ProviderCapability,
)

logger = logging.getLogger(__name__)


class ModelProvider(Protocol):
    async def create_plan(
        self, question: str, query: QuerySpec, tool_schemas: list[dict]
    ) -> dict: ...


class AttemptObserver(Protocol):
    async def before_attempt(self, attempt: int) -> Any: ...

    async def after_attempt(
        self, token: Any, *, succeeded: bool
    ) -> None: ...


class ProviderUnavailable(RuntimeError):
    pass


class StructuredOutputError(ProviderUnavailable):
    def __init__(self, message: str, *, raw_output: str = "") -> None:
        super().__init__(message)
        self.raw_output = raw_output


class OpenAICompatibleProvider:
    """Minimal structured-output adapter; it has no data or tool execution access."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        from financial_research_agent.capacity.provider import ProviderCapacity

        self.capacity = ProviderCapacity(settings)

    async def aclose(self) -> None:
        await self.capacity.aclose()

    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            provider=self.settings.model_provider,
            model_name=self.settings.model_name,
            context_window_tokens=self.settings.model_context_window_tokens,
            max_output_tokens=self.settings.model_max_output_tokens,
            thinking_mode=self.settings.model_thinking_mode,
        )

    async def create_plan(
        self, question: str, query: QuerySpec, tool_schemas: list[dict]
    ) -> dict:
        return (
            await self.create_plan_response(question, query, tool_schemas)
        ).content

    async def create_structured_response(
        self,
        *,
        instruction: str,
        input_payload: dict[str, Any],
        schema: type[BaseModel],
        max_tokens: int,
        operation: str,
        attempt_observer: AttemptObserver | None = None,
    ) -> ModelGatewayResponse:
        """Run a governed JSON-only model operation outside the main report schemas."""
        self._ensure_configured()
        prompt = {
            "instruction": instruction,
            "input": input_payload,
            "output_schema": schema.model_json_schema(),
            "operation": operation,
        }
        response = await self._request_json(
            self._base_payload(
                max_tokens=max_tokens,
                message=json.dumps(prompt, ensure_ascii=False),
            ),
            attempt_observer=attempt_observer,
        )
        validated = schema.model_validate(response.content)
        return response.model_copy(update={"content": validated.model_dump(mode="json")})

    async def create_plan_response(
        self,
        question: str,
        query: QuerySpec,
        tool_schemas: list[dict],
        *,
        attempt_observer: AttemptObserver | None = None,
        planning_context: dict[str, Any] | None = None,
    ) -> ModelGatewayResponse:
        self._ensure_configured()
        prompt = {
            "instruction": (
                "Return exactly one JSON object matching output_schema. Copy query_spec exactly "
                "into the top-level query field. Use top-level tasks, and for every task use "
                "task_id, tool_name, arguments, and depends_on. Use only the supplied read-only "
                "tools. Do not use steps/tool/params/output_var fields. Do not emit SQL, Python, "
                "Markdown, prose outside JSON, or unknown arguments. Legacy market analysis uses "
                "market_query and indicator_calculator; dedicated analysis intents use only the "
                "supplied technical, fundamental, event, factor or comparison tool. Follow "
                "query_spec.analysis_domains exactly and the visible Tool schemas. A "
                "comprehensive intent means multiple explicit domains; it does not authorize an "
                "unrequested domain."
            ),
            "question": question,
            "query_spec": query.model_dump(mode="json"),
            "tools": tool_schemas,
            "planning_context": planning_context,
            "output_schema": AnalysisPlan.model_json_schema(),
            "structure_example": {
                "query": query.model_dump(mode="json"),
                "tasks": [
                    {
                        "task_id": "task_identifier",
                        "tool_name": "one_name_from_supplied_tools",
                        "arguments": {"only": "arguments_allowed_by_that_tool_schema"},
                        "depends_on": [],
                    }
                ],
                "expected_sections": [query.intent.value],
            },
        }
        payload = self._base_payload(
            max_tokens=4096,
            message=json.dumps(prompt, ensure_ascii=False),
        )
        return await self._request_json(payload, attempt_observer=attempt_observer)

    async def create_report(
        self,
        question: str,
        report_context: dict,
        draft: dict | None = None,
        validation_errors: list[str] | None = None,
    ) -> dict:
        return (
            await self.create_report_response(
                question,
                report_context,
                draft=draft,
                validation_errors=validation_errors,
            )
        ).content

    async def create_report_response(
        self,
        question: str,
        report_context: dict,
        draft: dict | None = None,
        validation_errors: list[str] | None = None,
        *,
        attempt_observer: AttemptObserver | None = None,
    ) -> ModelGatewayResponse:
        self._ensure_configured()
        instruction = (
            "Return one JSON ResearchReport with subjects, summary, summary_evidence_ids, claims, "
            "structured risks, structured limitations, optional risk_vector and scenarios, "
            "data_as_of and disclaimer. The summary and "
            "every claim must cite evidence_ids from the supplied "
            "current-run evidence. For every claim citing research_report evidence, write the "
            "exact institution from each cited evidence item directly in the claim text, including "
            "claims that describe factual events. When repairing REPORT_ATTRIBUTION_MISSING, locate "
            "the cited evidence ID in report_context and add its exact institution to that claim. "
            "A report_candidate item supports only report title, institution, date, rank and "
            "coverage statements; never use it for report viewpoints, ratings, target prices, "
            "forecasts, catalysts or risks. When report_context.report_facts is present, copy the "
            "matching fact_id into a claim's fact_ids for target prices, ratings, forecasts and "
            "other structured report facts. Never invent a fact_id. Numbers from market, financial "
            "or calculation Evidence must appear in the text or structured data of at least one "
            "Evidence item cited by that same section. A high-risk research-report number must match "
            "a supplied report_fact linked to the same cited Evidence. Preserve negative directions "
            "such as decline and price fall; a drawdown may be stated as a positive magnitude. "
            "Do not cite one report chunk for a number that "
            "only appears in another chunk. A research-report claim containing numbers must use "
            "numbers from one evidence chunk only; split information from different chunks into "
            "separate claims. When repairing NUMERIC_UNSUPPORTED, either split the claim and cite "
            "the exact current-run evidence ID containing each number, or remove the unsupported "
            "number. Every risk must be an object with risk, classification, evidence_ids and "
            "confidence; classification is fact, calculation or model_interpretation. Every risk "
            "must cite current-run evidence, and calculation risks must cite calculation evidence. "
            "Every limitation must be an object with limitation, category and evidence_ids; category "
            "is data, scope or method. Do not add facts or calculate numbers that are absent from "
            "cited evidence. Risk-vector dimensions outside query.analysis_domains must use level "
            "unknown with no evidence_ids; do not infer an unrequested event or fundamental risk "
            "from background knowledge. This is research, not investment advice."
        )
        prompt = {
            "instruction": instruction,
            "question": question,
            "report_context": report_context,
            "draft": draft,
            "validation_errors": validation_errors or [],
            "output_schema": ResearchReport.model_json_schema(),
            "structure_example": {
                "subjects": report_context["query"]["stock_codes"],
                "summary": "A concise evidence-based summary without unsupported facts.",
                "summary_evidence_ids": [
                    "copy_an_exact_evidence_id_from_report_context"
                ],
                "claims": [
                    {
                        "claim": "A claim supported by the cited current-run evidence.",
                        "evidence_ids": ["copy_an_exact_evidence_id_from_report_context"],
                        "fact_ids": [],
                        "confidence": "medium",
                    }
                ],
                "risks": [
                    {
                        "risk": "An evidence-aware risk or uncertainty.",
                        "classification": "model_interpretation",
                        "evidence_ids": [
                            "copy_an_exact_evidence_id_from_report_context"
                        ],
                        "confidence": "medium",
                    }
                ],
                "limitations": [
                    {
                        "limitation": "State a material data or scope limitation.",
                        "category": "scope",
                        "evidence_ids": [],
                    }
                ],
                "risk_vector": [
                    {"dimension": "technical", "level": "unknown", "rationale": "No technical Evidence when absent.", "evidence_ids": []},
                    {"dimension": "fundamental", "level": "unknown", "rationale": "No fundamental Evidence when absent.", "evidence_ids": []},
                    {"dimension": "event", "level": "unknown", "rationale": "No event Evidence when absent.", "evidence_ids": []},
                    {"dimension": "data_confidence", "level": "medium", "rationale": "Explain source coverage without unsupported numbers.", "evidence_ids": ["copy_an_exact_evidence_id_from_report_context"]}
                ],
                "scenarios": [
                    {"name": "optimistic", "assumptions": ["Evidence-grounded assumption"], "implication": "Conditional implication, not a forecast.", "evidence_ids": ["copy_an_exact_evidence_id_from_report_context"]},
                    {"name": "base", "assumptions": ["Evidence-grounded assumption"], "implication": "Conditional implication, not a forecast.", "evidence_ids": ["copy_an_exact_evidence_id_from_report_context"]},
                    {"name": "stress", "assumptions": ["Evidence-grounded assumption"], "implication": "Conditional implication, not a forecast.", "evidence_ids": ["copy_an_exact_evidence_id_from_report_context"]}
                ],
                "data_as_of": "YYYY-MM-DD or null when evidence has no determinable date",
                "disclaimer": "仅供研究参考，不构成投资建议。",
            },
        }
        payload = self._base_payload(
            max_tokens=8192,
            message=json.dumps(prompt, ensure_ascii=False),
        )
        return await self._request_json(payload, attempt_observer=attempt_observer)

    async def create_context_summary_response(
        self,
        context: dict[str, Any],
        *,
        attempt_observer: AttemptObserver | None = None,
    ) -> ModelGatewayResponse:
        self._ensure_configured()
        prompt = {
            "instruction": (
                "Return exactly one JSON object with a summary field. "
                "Summarize only the supplied session and preference context. "
                "Do not add facts, numbers, entities, credentials, investment "
                "conclusions, Evidence, source locators, or hidden reasoning."
            ),
            "context": context,
            "output_schema": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
                "additionalProperties": False,
            },
        }
        payload = self._base_payload(
            max_tokens=1024,
            message=json.dumps(prompt, ensure_ascii=False),
        )
        return await self._request_json(
            payload, attempt_observer=attempt_observer
        )

    def _base_payload(self, *, max_tokens: int, message: str) -> dict:
        payload = {
            "model": self.settings.model_name,
            "messages": [{"role": "user", "content": message}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        if self.settings.model_thinking_mode != "omit":
            payload["thinking"] = {"type": self.settings.model_thinking_mode}
        if self.settings.model_thinking_mode == "enabled":
            payload["reasoning_effort"] = self.settings.model_reasoning_effort
            payload.pop("temperature", None)
        return payload

    async def _request_json(
        self,
        payload: dict,
        *,
        attempt_observer: AttemptObserver | None = None,
    ) -> ModelGatewayResponse:
        headers = {"Authorization": f"Bearer {self.settings.model_api_key}"}
        url = f"{self.settings.model_base_url.rstrip('/')}/chat/completions"
        timeout = httpx.Timeout(self.settings.model_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(self.settings.model_max_retries + 1):
                observer_token = (
                    await attempt_observer.before_attempt(attempt)
                    if attempt_observer is not None
                    else None
                )
                try:
                    async with self.capacity.slot():
                        response = await client.post(
                            url, headers=headers, json=payload
                        )
                    response.raise_for_status()
                    if attempt_observer is not None:
                        await attempt_observer.after_attempt(
                            observer_token, succeeded=True
                        )
                    break
                except httpx.TransportError as exc:
                    if attempt_observer is not None:
                        await attempt_observer.after_attempt(
                            observer_token, succeeded=False
                        )
                    if attempt >= self.settings.model_max_retries:
                        raise
                    await self._retry_delay(attempt, exc)
                except httpx.HTTPStatusError as exc:
                    if attempt_observer is not None:
                        await attempt_observer.after_attempt(
                            observer_token, succeeded=False
                        )
                    if (
                        exc.response.status_code
                        not in {408, 409, 425, 429, 500, 502, 503, 504}
                        or attempt >= self.settings.model_max_retries
                    ):
                        raise
                    await self._retry_delay(attempt, exc)
                except Exception:
                    if attempt_observer is not None:
                        await attempt_observer.after_attempt(
                            observer_token, succeeded=False
                        )
                    raise
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        if not content or not content.strip():
            raise ProviderUnavailable("model returned empty content")
        parsed = json.loads(content)
        usage = self._usage(
            body.get("usage"),
            payload=payload,
            content=content,
        )
        return ModelGatewayResponse(
            content=parsed,
            usage=usage,
            provider_request_id=body.get("id"),
        )

    def _usage(
        self,
        raw: dict | None,
        *,
        payload: dict,
        content: str,
    ) -> ModelUsage:
        if raw:
            input_tokens = int(raw.get("prompt_tokens") or 0)
            output_tokens = int(raw.get("completion_tokens") or 0)
            hit = int(raw.get("prompt_cache_hit_tokens") or 0)
            miss = int(raw.get("prompt_cache_miss_tokens") or 0)
            total = int(raw.get("total_tokens") or input_tokens + output_tokens)
            estimated = False
        else:
            input_tokens = max(
                1,
                len(
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                )
                // 3,
            )
            output_tokens = max(1, len(content) // 3)
            hit = 0
            miss = input_tokens
            total = input_tokens + output_tokens
            estimated = True
        cost = self._cost_microunits(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_hit_tokens=hit,
            cache_miss_tokens=miss,
        )
        return ModelUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total,
            cache_hit_tokens=hit,
            cache_miss_tokens=miss,
            estimated=estimated,
            cost_microunits=cost,
        )

    def _cost_microunits(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_hit_tokens: int,
        cache_miss_tokens: int,
    ) -> int | None:
        input_price = self.settings.model_input_price_cny_per_million
        output_price = self.settings.model_output_price_cny_per_million
        if input_price is None or output_price is None:
            return None
        hit_price = self.settings.model_cache_hit_price_cny_per_million
        if cache_hit_tokens or cache_miss_tokens:
            input_cost = cache_miss_tokens * input_price
            input_cost += cache_hit_tokens * (
                hit_price if hit_price is not None else input_price
            )
        else:
            input_cost = input_tokens * input_price
        cny = (input_cost + output_tokens * output_price) / 1_000_000
        return max(0, int(round(cny * 1_000_000)))

    def _ensure_configured(self) -> None:
        if (
            not self.settings.model_name
            or not self.settings.model_api_key
            or not self.settings.model_base_url
        ):
            raise ProviderUnavailable("model provider is not configured")

    async def _retry_delay(self, attempt: int, exc: Exception) -> None:
        delay = min(
            self.settings.model_retry_backoff_seconds * (2**attempt),
            self.settings.model_retry_max_backoff_seconds,
        )
        response = getattr(exc, "response", None)
        if response is not None:
            raw_retry_after = response.headers.get("retry-after")
            if raw_retry_after:
                try:
                    delay = max(
                        delay,
                        min(
                            float(raw_retry_after),
                            self.settings.model_retry_max_backoff_seconds,
                        ),
                    )
                except ValueError:
                    pass
        logger.warning(
            "model_request_retry attempt=%s max_retries=%s delay_seconds=%s error=%s",
            attempt + 1,
            self.settings.model_max_retries,
            delay,
            type(exc).__name__,
        )
        if delay:
            await asyncio.sleep(delay)


def build_model_provider(settings: Settings) -> OpenAICompatibleProvider:
    if settings.agent_framework == "langchain":
        from financial_research_agent.integrations.langchain.model import (
            LangChainModelProvider,
        )

        return LangChainModelProvider(settings)
    return OpenAICompatibleProvider(settings)
