from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from types import SimpleNamespace

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import (
    AnalysisPlan,
    AnalysisTask,
    Evidence,
    Intent,
    QuerySpec,
    ResearchReport,
    SourceReference,
    ToolName,
    ToolResult,
)
from financial_research_agent.governance.gateways import ToolGateway
from financial_research_agent.integrations.langchain.model import (
    LangChainModelProvider,
)
from financial_research_agent.orchestration.registry import ToolRegistry
from financial_research_agent.providers.model import (
    StructuredOutputError,
    build_model_provider,
)
from financial_research_agent.skills.registry import SkillRegistry
from financial_research_agent.tools.base import FinancialTool, ToolDefinition


class PriceInput(BaseModel):
    stock_code: str


class PriceTool(FinancialTool):
    definition = ToolDefinition(
        name="market_query",
        description="Query governed market data.",
        data_domain="market",
    )
    input_model = PriceInput

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, task_id: str, arguments: BaseModel) -> ToolResult:
        self.calls += 1
        return ToolResult(
            task_id=task_id,
            success=True,
            evidence=[
                Evidence(
                    evidence_id="market-evidence",
                    evidence_type="market",
                    subject=arguments.stock_code,
                    statement="行情数据已返回。",
                    source=SourceReference(
                        source_type="iceberg",
                        locator="iceberg://market/600519",
                        observed_at=datetime.now(UTC),
                    ),
                )
            ],
            latency_ms=1,
        )


class FakePolicy:
    async def authorize_tool(self, *, tool, arguments, **_):
        return (
            SimpleNamespace(decision_id="decision-1"),
            tool.validate_input(arguments),
        )


class FakeGovernance:
    def __init__(self) -> None:
        self.reservations = 0

    async def reserve(self, **_):
        self.reservations += 1
        return SimpleNamespace(
            entry_id=f"budget-{self.reservations}",
            status="reserved",
        )

    async def commit(self, _entry_id):
        return None

    async def release(self, _entry_id):
        return None


class FakeBusiness:
    async def reserve_tool_call(self, **_):
        return SimpleNamespace(
            execute=True,
            call_id="tool-call-1",
            result_payload=None,
        )

    async def record_tool_attempts(self, *_args, **_kwargs):
        return None

    async def complete_tool_call(self, *_args, **_kwargs):
        return None

    async def fail_tool_call(self, *_args, **_kwargs):
        return None


class FakeStructuredModel:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def with_structured_output(
        self,
        schema,
        *,
        method: str,
        include_raw: bool,
    ):
        async def invoke(_messages):
            parsed = schema.model_validate(self.payload)
            return {
                "parsed": parsed,
                "parsing_error": None,
                "raw": AIMessage(
                    content="",
                    id="langchain-request",
                    usage_metadata={
                        "input_tokens": 20,
                        "output_tokens": 10,
                        "total_tokens": 30,
                    },
                ),
            }

        return RunnableLambda(invoke)


class RetryStructuredModel:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def with_structured_output(
        self,
        schema,
        *,
        method: str,
        include_raw: bool,
    ):
        async def invoke(_messages):
            self.calls += 1
            if self.calls == 1:
                return {
                    "parsed": None,
                    "parsing_error": ValueError("invalid structured output"),
                    "raw": AIMessage(content="{}"),
                }
            return {
                "parsed": schema.model_validate(self.payload),
                "parsing_error": None,
                "raw": AIMessage(
                    content="",
                    usage_metadata={
                        "input_tokens": 20,
                        "output_tokens": 10,
                        "total_tokens": 30,
                    },
                ),
            }

        return RunnableLambda(invoke)


class LangChainCoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            agent_framework="langchain",
            model_name="deepseek-v4-flash",
            model_api_key="test-key",
            model_base_url="https://api.deepseek.com",
            model_max_retries=0,
        )
        self.query = QuerySpec(
            stock_codes=["600519"],
            start_date=date(2026, 6, 1),
            end_date=date(2026, 7, 1),
            intent=Intent.MARKET,
            dimensions=["trend"],
        )

    async def test_factory_and_structured_plan_use_langchain_runnable(self):
        plan = {
            "query": self.query.model_dump(mode="json"),
            "tasks": [
                {
                    "task_id": "market",
                    "tool_name": "market_query",
                    "arguments": {"stock_code": "600519"},
                    "depends_on": [],
                }
            ],
            "expected_sections": ["market"],
        }
        provider = build_model_provider(self.settings)
        self.assertIsInstance(provider, LangChainModelProvider)
        provider._chat_model = lambda **_: FakeStructuredModel(plan)

        response = await provider.create_plan_response(
            "分析贵州茅台走势",
            self.query,
            [{"name": "market_query", "input_schema": {"type": "object"}}],
        )

        self.assertEqual(
            AnalysisPlan.model_validate(response.content).tasks[0].task_id,
            "market",
        )
        self.assertEqual(response.usage.total_tokens, 30)
        self.assertEqual(response.message["type"], "ai")

        report_payload = {
            "subjects": ["600519"],
            "summary": "基于当前证据形成报告。",
            "summary_evidence_ids": ["market-evidence"],
            "claims": [
                {
                    "claim": "行情数据已返回。",
                    "evidence_ids": ["market-evidence"],
                    "confidence": "medium",
                }
            ],
            "risks": [{"risk": "样本区间有限。", "classification": "model_interpretation", "evidence_ids": ["market-evidence"], "confidence": "medium"}],
            "limitations": [{"limitation": "仅用于框架冒烟验证。", "category": "scope", "evidence_ids": []}],
            "data_as_of": "2026-07-01",
            "disclaimer": "仅供研究参考，不构成投资建议。",
        }
        provider._chat_model = lambda **_: FakeStructuredModel(report_payload)
        report_response = await provider.create_report_response(
            "分析贵州茅台走势",
            {
                "query": self.query.model_dump(mode="json"),
                "evidence": [{"evidence_id": "market-evidence"}],
            },
        )
        self.assertEqual(
            ResearchReport.model_validate(report_response.content).subjects,
            ["600519"],
        )

    async def test_structured_output_validation_failure_is_not_blindly_retried(self):
        plan = {
            "query": self.query.model_dump(mode="json"),
            "tasks": [
                {
                    "task_id": "market",
                    "tool_name": "market_query",
                    "arguments": {"stock_code": "600519"},
                    "depends_on": [],
                }
            ],
            "expected_sections": ["market"],
        }
        provider = LangChainModelProvider(
            self.settings.model_copy(
                update={
                    "model_max_retries": 1,
                    "model_retry_backoff_seconds": 0,
                }
            )
        )
        model = RetryStructuredModel(plan)
        provider._chat_model = lambda **_: model

        with self.assertRaises(StructuredOutputError) as caught:
            await provider.create_plan_response(
                "分析贵州茅台走势",
                self.query,
                [{"name": "market_query", "input_schema": {"type": "object"}}],
            )

        self.assertEqual(model.calls, 1)
        self.assertEqual(caught.exception.raw_output, "{}")

    async def test_tool_gateway_executes_structured_tool_and_returns_artifact(self):
        tool = PriceTool()
        registry = ToolRegistry()
        registry.register(tool)
        gateway = ToolGateway(
            self.settings.model_copy(update={"max_tool_retries": 0}),
            registry,
            FakeBusiness(),
            FakeGovernance(),
            FakePolicy(),
        )
        plan = AnalysisPlan(
            query=self.query,
            tasks=[
                AnalysisTask(
                    task_id="market",
                    tool_name=ToolName.MARKET_QUERY,
                    arguments={"stock_code": "600519"},
                )
            ],
        )
        selection = SkillRegistry.from_builtin_catalog().select(
            self.query, {item.value for item in ToolName}
        )

        results, messages = await gateway.execute_with_messages(
            run_id="langchain-smoke",
            plan=plan,
            selection=selection,
        )

        self.assertEqual(tool.calls, 1)
        self.assertTrue(results[0].success)
        self.assertEqual(messages[0]["type"], "tool")
        self.assertTrue(messages[0]["data"]["artifact"]["tool_result"]["success"])
        self.assertEqual(messages[0]["data"]["artifact"]["data_domain"], "market")


if __name__ == "__main__":
    unittest.main()
