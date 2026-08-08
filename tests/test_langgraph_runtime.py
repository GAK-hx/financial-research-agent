from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from pydantic import BaseModel

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import (
    Evidence,
    ReportClaim,
    ResearchReport,
    SourceReference,
    ToolResult,
)
from financial_research_agent.orchestration.executor import PlanExecutor
from financial_research_agent.orchestration.interpreter import QueryInterpreter
from financial_research_agent.orchestration.planner import RulePlanner, StructuredPlanner
from financial_research_agent.orchestration.registry import ToolRegistry
from financial_research_agent.orchestration.service import OrchestrationService
from financial_research_agent.orchestration.validator import PlanValidator
from financial_research_agent.reporting.service import ReportingService
from financial_research_agent.reporting.validators import ReportValidator
from financial_research_agent.research import ResearchService
from financial_research_agent.tools.base import FinancialTool, ToolDefinition

try:
    from langgraph.checkpoint.memory import InMemorySaver

    from financial_research_agent.orchestration.langgraph_runtime import (
        LangGraphResearchService,
        ensure_json_safe_graph_state,
        initial_research_state,
        research_graph_config,
    )

    LANGGRAPH_AVAILABLE = True
except ModuleNotFoundError:
    LANGGRAPH_AVAILABLE = False


class FinancialInput(BaseModel):
    stock_code: str
    start_date: date | None = None
    end_date: date | None = None


class ControlledFinancialTool(FinancialTool):
    definition = ToolDefinition(
        name="financial_query",
        description="Controlled read-only financial data.",
        data_domain="financial",
        timeout_seconds=2,
    )
    input_model = FinancialInput

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def execute(self, task_id: str, arguments: FinancialInput) -> ToolResult:
        self.calls += 1
        if self.fail:
            return ToolResult(
                task_id=task_id,
                success=False,
                error_code="SOURCE_UNAVAILABLE",
                error_message="controlled failure",
                latency_ms=1,
            )
        return ToolResult(
            task_id=task_id,
            success=True,
            evidence=[
                Evidence(
                    evidence_id="financial-controlled",
                    evidence_type="financial",
                    subject=arguments.stock_code,
                    statement="公司财务表现已有可追溯数据支持。",
                    data={"metric": "controlled"},
                    source=SourceReference(
                        source_type="iceberg",
                        locator=f"iceberg://controlled/{arguments.stock_code}",
                        observed_at=datetime.now(timezone.utc),
                    ),
                )
            ],
            latency_ms=1,
        )


class ControlledReporter:
    def __init__(self, *, invalid_first: bool = False) -> None:
        self.invalid_first = invalid_first
        self.calls = 0

    async def generate(
        self,
        question,
        query,
        evidence,
        draft=None,
        validation_errors=None,
    ) -> ResearchReport:
        self.calls += 1
        subjects = (
            ["300750"]
            if self.invalid_first and self.calls == 1
            else query.stock_codes
        )
        return ResearchReport(
            subjects=subjects,
            summary="基于受控证据完成财务研究。",
            summary_evidence_ids=[evidence[0].evidence_id],
            claims=[
                ReportClaim(
                    claim="公司财务表现已有可追溯数据支持。",
                    evidence_ids=[evidence[0].evidence_id],
                    confidence="high",
                )
            ],
            risks=[{"risk": "数据覆盖范围有限。", "classification": "model_interpretation", "evidence_ids": [evidence[0].evidence_id], "confidence": "medium"}],
            limitations=[{"limitation": "仅验证状态迁移。", "category": "scope", "evidence_ids": []}],
        )


def build_services(*, fail_tool: bool = False, invalid_first: bool = False):
    settings = Settings(
        evaluation_reference_date=date(2026, 7, 15),
        max_tool_retries=0,
        max_report_revisions=1,
        checkpoint_backend="memory",
    )
    registry = ToolRegistry()
    tool = ControlledFinancialTool(fail=fail_tool)
    registry.register(tool)
    orchestration = OrchestrationService(
        settings,
        registry,
        provider=None,
        interpreter=QueryInterpreter(today=settings.evaluation_reference_date),
    )
    orchestration.planner = StructuredPlanner(
        registry, RulePlanner(registry), provider=None
    )
    orchestration.validator = PlanValidator(settings, registry)
    orchestration.executor = PlanExecutor(registry, max_parallel=2, max_retries=0)
    reporter = ControlledReporter(invalid_first=invalid_first)
    reporting = ReportingService(settings, reporter, ReportValidator())
    return settings, tool, reporter, orchestration, reporting


@unittest.skipUnless(LANGGRAPH_AVAILABLE, "LangGraph is isolated to the harness profile")
class LangGraphRuntimeTests(unittest.IsolatedAsyncioTestCase):
    question = "分析贵州茅台最近三年的营收和利润"

    async def test_full_graph_has_one_terminal_write_and_json_safe_state(self) -> None:
        settings, tool, _, orchestration, reporting = build_services()
        service = LangGraphResearchService(
            settings,
            orchestration=orchestration,
            reporting=reporting,
            checkpointer=InMemorySaver(),
        )
        initial = initial_research_state(self.question, "graph-complete")
        state = await service.graph.ainvoke(
            initial, research_graph_config(initial["thread_id"])
        )

        ensure_json_safe_graph_state(state)
        self.assertEqual(state["terminal_writes"], 1)
        self.assertEqual(state["reporting_status"], "completed")
        self.assertEqual(
            state["node_trace"],
            [
                "load_memory",
                "interpret",
                "align_semantics",
                "remember_query",
                "select_skill",
                "initialize_governance",
                "plan",
                "validate_plan",
                "execute_tools",
                "build_evidence",
                "check_evidence_sufficiency",
                "generate_report",
                "validate_report",
                "completion_check",
                "finalize",
            ],
        )
        self.assertEqual(tool.calls, 1)
        self.assertEqual(
            state["skill_selection"]["snapshots"][0]["version_id"],
            "financial_growth_analysis@1.0.0",
        )

    async def test_report_revision_is_an_explicit_graph_path(self) -> None:
        settings, _, reporter, orchestration, reporting = build_services(
            invalid_first=True
        )
        service = LangGraphResearchService(
            settings, orchestration=orchestration, reporting=reporting
        )
        result = await service.analyze(self.question)
        snapshot = await service.graph.aget_state(
            research_graph_config(result.orchestration.run_id)
        )

        self.assertTrue(result.success)
        self.assertEqual(result.reporting.attempts, 2)
        self.assertEqual(reporter.calls, 2)
        self.assertIn("revise_report", snapshot.values["node_trace"])
        self.assertEqual(snapshot.values["terminal_writes"], 1)

    async def test_tool_failure_reaches_controlled_terminal_state(self) -> None:
        settings, tool, _, orchestration, reporting = build_services(fail_tool=True)
        service = LangGraphResearchService(
            settings, orchestration=orchestration, reporting=reporting
        )
        result = await service.analyze(self.question)
        snapshot = await service.graph.aget_state(
            research_graph_config(result.orchestration.run_id)
        )

        self.assertFalse(result.success)
        self.assertFalse(result.orchestration.success)
        self.assertIsNone(result.reporting)
        self.assertEqual(result.orchestration.errors[0].split(":")[1], "SOURCE_UNAVAILABLE")
        self.assertNotIn("generate_report", snapshot.values["node_trace"])
        self.assertEqual(snapshot.values["terminal_writes"], 1)
        self.assertEqual(tool.calls, 1)

    async def test_legacy_and_graph_results_are_semantically_equivalent(self) -> None:
        legacy_parts = build_services()
        graph_parts = build_services()
        legacy = ResearchService(
            legacy_parts[0],
            orchestration=legacy_parts[3],
            reporting=legacy_parts[4],
        )
        graph = LangGraphResearchService(
            graph_parts[0],
            orchestration=graph_parts[3],
            reporting=graph_parts[4],
        )

        legacy_result = await legacy.analyze(self.question)
        graph_result = await graph.analyze(self.question)

        self.assertEqual(legacy_result.success, graph_result.success)
        self.assertEqual(
            legacy_result.orchestration.query, graph_result.orchestration.query
        )
        self.assertEqual(
            legacy_result.orchestration.plan.model_dump(mode="json"),
            graph_result.orchestration.plan.model_dump(mode="json"),
        )
        self.assertEqual(
            [item.success for item in legacy_result.orchestration.tool_results],
            [item.success for item in graph_result.orchestration.tool_results],
        )
        self.assertEqual(
            [item.statement for item in legacy_result.orchestration.evidence],
            [item.statement for item in graph_result.orchestration.evidence],
        )
        def normalize_run_evidence_ids(value, run_id):
            if isinstance(value, dict):
                return {
                    key: normalize_run_evidence_ids(item, run_id)
                    for key, item in value.items()
                }
            if isinstance(value, list):
                return [
                    normalize_run_evidence_ids(item, run_id) for item in value
                ]
            if isinstance(value, str) and value.startswith(f"{run_id}:"):
                return value[len(run_id) + 1 :]
            return value

        self.assertEqual(
            normalize_run_evidence_ids(
                legacy_result.reporting.report.model_dump(),
                legacy_result.orchestration.run_id,
            ),
            normalize_run_evidence_ids(
                graph_result.reporting.report.model_dump(),
                graph_result.orchestration.run_id,
            ),
        )
        self.assertEqual(
            legacy_result.reporting.validation.passed,
            graph_result.reporting.validation.passed,
        )


if __name__ == "__main__":
    unittest.main()
