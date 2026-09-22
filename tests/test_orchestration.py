from __future__ import annotations

import asyncio
import unittest
from datetime import date, datetime, timezone

from pydantic import BaseModel

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import (
    AnalysisPlan,
    AnalysisTask,
    Evidence,
    Intent,
    SourceReference,
    ToolName,
    ToolResult,
)
from financial_research_agent.orchestration.executor import PlanExecutor
from financial_research_agent.orchestration.interpreter import QueryInterpreter
from financial_research_agent.orchestration.planner import RulePlanner, StructuredPlanner
from financial_research_agent.orchestration.registry import ToolRegistry
from financial_research_agent.orchestration.semantic import SemanticAlignmentValidator
from financial_research_agent.orchestration.service import OrchestrationService
from financial_research_agent.orchestration.validator import PlanValidator
from financial_research_agent.tools.base import FinancialTool, ToolDefinition


class AnyInput(BaseModel):
    stock_code: str | None = None
    stock_codes: list[str] | None = None
    start_date: date | None = None
    end_date: date | None = None
    adjust_type: str | None = None
    query: str | None = None


class ControlledTool(FinancialTool):
    input_model = AnyInput

    def __init__(
        self,
        name: str,
        domain: str,
        calls: list[str],
        delay: float = 0,
        failures_before_success: int = 0,
    ) -> None:
        self.definition = ToolDefinition(
            name=name,
            description=f"controlled {name}",
            data_domain=domain,
            timeout_seconds=2,
        )
        self.calls = calls
        self.delay = delay
        self.failures_before_success = failures_before_success
        self.attempts = 0

    async def execute(self, task_id: str, arguments: AnyInput) -> ToolResult:
        self.attempts += 1
        self.calls.append(f"start:{task_id}")
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.attempts <= self.failures_before_success:
            self.calls.append(f"fail:{task_id}")
            return ToolResult(
                task_id=task_id,
                success=False,
                error_code="SOURCE_UNAVAILABLE",
                error_message="temporary",
                latency_ms=0,
            )
        self.calls.append(f"end:{task_id}")
        evidence = Evidence(
            evidence_id=f"{task_id}-{arguments.stock_code}",
            evidence_type=(
                "report_candidate"
                if self.definition.name == "report_candidate_search"
                else "research_report"
                if self.definition.name in {"report_search", "report_content_search"}
                else "financial"
                if self.definition.name == "financial_query"
                else "indicator"
                if self.definition.name == "indicator_calculator"
                else "market"
            ),
            subject=arguments.stock_code,
            statement=f"evidence from {task_id}",
            data=(
                {
                    "institution": "测试证券",
                    "report_title": "测试研报",
                    "page_number": 1,
                    "chunk_id": "chunk-test",
                }
                if self.definition.name in {"report_search", "report_content_search"}
                else {
                    "candidate_id": "rpt_0123456789abcdef",
                    "candidate_set_id": "rcs_0123456789abcdef",
                    "document_id": "document-test",
                    "stock_code": arguments.stock_code,
                    "institution": "测试证券",
                    "report_title": "测试研报",
                    "report_date": "2026-07-01",
                    "rank": 1,
                    "applied_start_date": "2026-01-16",
                    "applied_end_date": "2026-07-15",
                    "coverage_status": "limited",
                }
                if self.definition.name == "report_candidate_search"
                else {}
            ),
            source=SourceReference(
                source_type=(
                    "milvus"
                    if self.definition.name in {
                        "report_search",
                        "report_candidate_search",
                        "report_content_search",
                    }
                    else "calculation"
                    if self.definition.name == "indicator_calculator"
                    else "iceberg"
                ),
                locator=f"test://{task_id}",
                observed_at=datetime.now(timezone.utc),
                metadata=(
                    {"page_number": 1, "document_id": "document-test"}
                    if self.definition.name in {"report_search", "report_content_search"}
                    else {"document_id": "document-test"}
                    if self.definition.name == "report_candidate_search"
                    else {
                        "formula_version": "test-v1",
                        "input_locator": "test://market",
                    }
                    if self.definition.name == "indicator_calculator"
                    else {}
                ),
            ),
        )
        return ToolResult(task_id=task_id, success=True, evidence=[evidence], latency_ms=0)


def controlled_registry(calls: list[str] | None = None) -> ToolRegistry:
    calls = calls if calls is not None else []
    registry = ToolRegistry()
    registry.register(ControlledTool("market_query", "market", calls, delay=0.02))
    registry.register(ControlledTool("indicator_calculator", "market", calls))
    registry.register(ControlledTool("financial_query", "financial", calls))
    registry.register(
        ControlledTool(
            "report_candidate_search", "research_report", calls, delay=0.02
        )
    )
    registry.register(
        ControlledTool("report_content_search", "research_report", calls, delay=0.02)
    )
    registry.register(ControlledTool("stock_comparison", "market", calls))
    return registry


class InvalidProvider:
    async def create_plan(self, question: str, query, tool_schemas: list[dict]) -> dict:
        return {"invalid": True}


class InterpreterTests(unittest.TestCase):
    def test_fifteen_questions(self):
        interpreter = QueryInterpreter(today=date(2026, 7, 15))
        cases = [
            ("贵州茅台最近一个月股价走势", "600519", Intent.MARKET, date(2026, 6, 15)),
            ("宁德时代近三个月收益率", "300750", Intent.MARKET, date(2026, 4, 15)),
            ("宁德时代最近六个月行情", "300750", Intent.MARKET, date(2026, 1, 15)),
            ("600519近30天成交量", "600519", Intent.MARKET, date(2026, 6, 15)),
            ("300750近1年最大回撤", "300750", Intent.MARKET, date(2025, 7, 15)),
            ("贵州茅台今年行情", "600519", Intent.MARKET, date(2026, 1, 1)),
            ("宁德时代去年股价表现", "300750", Intent.MARKET, date(2025, 1, 1)),
            ("贵州茅台的最新研报观点", "600519", Intent.REPORT, None),
            ("宁德时代机构如何看技术创新", "300750", Intent.REPORT, None),
            ("600519券商观点", "600519", Intent.REPORT, None),
            ("300750研究报告怎么看补能生态", "300750", Intent.REPORT, None),
            ("贵州茅台最近一年股价和研报观点", "600519", Intent.COMPREHENSIVE, date(2025, 7, 15)),
            ("宁德时代近6个月行情与机构观点", "300750", Intent.COMPREHENSIVE, date(2026, 1, 15)),
            ("贵州茅台最近三年营收和利润", "600519", Intent.FINANCIAL, date(2023, 7, 15)),
            ("宁德时代今年毛利率和负债率", "300750", Intent.FINANCIAL, date(2026, 1, 1)),
            ("600519从2026-01-01到2026-06-30的波动率", "600519", Intent.MARKET, date(2026, 1, 1)),
        ]
        for question, stock, intent, expected_start in cases:
            with self.subTest(question=question):
                spec = interpreter.interpret(question)
                self.assertEqual(spec.stock_codes, [stock])
                self.assertEqual(spec.intent, intent)
                self.assertEqual(spec.start_date, expected_start)

    def test_unknown_stock_is_not_guessed(self):
        with self.assertRaises(ValueError):
            QueryInterpreter(today=date(2026, 7, 15)).interpret("某家公司最近股价如何")

    def test_multi_stock_technical_comparison_routes_to_screening(self):
        query = QueryInterpreter(today=date(2026, 8, 8)).interpret(
            "比较600519、300750、601318从2025-08-01到2026-08-07的"
            "技术面、波动率、最大回撤与流动性"
        )

        self.assertEqual(query.intent, Intent.SCREENING)
        self.assertEqual(query.stock_codes, ["600519", "300750", "601318"])

    def test_complete_periods_preserve_granularity_and_boundaries(self):
        interpreter = QueryInterpreter(today=date(2026, 7, 15))
        cases = [
            ("贵州茅台最近一个完整交易月行情", "month", date(2026, 6, 1), date(2026, 6, 30)),
            ("贵州茅台最近一个完整季度行情", "quarter", date(2026, 4, 1), date(2026, 6, 30)),
            ("贵州茅台最近一个完整年行情", "year", date(2025, 1, 1), date(2025, 12, 31)),
            ("贵州茅台最近一个完整交易日行情", "day", date(2026, 7, 14), date(2026, 7, 14)),
        ]
        for question, granularity, start, end in cases:
            with self.subTest(question=question):
                query = interpreter.interpret(question)
                self.assertEqual(query.start_date, start)
                self.assertEqual(query.end_date, end)
                self.assertEqual(query.time_scope.granularity, granularity)
                self.assertTrue(query.time_scope.complete_period)
                alignment = SemanticAlignmentValidator(interpreter).validate(
                    question, query
                )
                self.assertTrue(alignment.passed, alignment.errors)

    def test_semantic_alignment_rejects_range_and_domain_drift(self):
        interpreter = QueryInterpreter(today=date(2026, 7, 15))
        question = "贵州茅台最近一个完整交易月行情"
        query = interpreter.interpret(question)
        corrupted = query.model_copy(
            update={
                "start_date": date(2025, 1, 1),
                "analysis_domains": ["financial"],
            }
        )
        result = SemanticAlignmentValidator(interpreter).validate(
            question, corrupted
        )
        self.assertFalse(result.passed)
        self.assertIn("TIME_SCOPE_QUERY_RANGE_MISMATCH", result.errors)
        self.assertTrue(
            any("ANALYSIS_DOMAIN_SCOPE_MISMATCH" in item for item in result.errors)
        )

    def test_ambiguous_recent_expression_is_not_silently_defaulted(self):
        interpreter = QueryInterpreter(today=date(2026, 7, 15))
        question = "贵州茅台近期股价如何"
        query = interpreter.interpret(question)
        result = SemanticAlignmentValidator(interpreter).validate(
            question, query
        )
        self.assertFalse(result.passed)
        self.assertIn("TIME_EXPRESSION_AMBIGUOUS", result.errors)


class PlannerValidatorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = controlled_registry()
        self.settings = Settings(max_plan_tasks=6, max_tool_calls=8)
        self.interpreter = QueryInterpreter(today=date(2026, 7, 15))

    async def test_standard_trajectories_and_model_fallback(self):
        planner = StructuredPlanner(self.registry, RulePlanner(self.registry), InvalidProvider())
        cases = {
            "贵州茅台最近一个月股价走势": ["market", "indicator"],
            "贵州茅台最新研报观点": ["report_candidates"],
            "贵州茅台最近一年股价和研报观点": ["market", "indicator", "report_candidates"],
            "贵州茅台最近一年营收和利润": ["financial"],
        }
        for question, task_ids in cases.items():
            query = self.interpreter.interpret(question)
            plan, source = await planner.create_plan(question, query)
            self.assertEqual([task.task_id for task in plan.tasks], task_ids)
            self.assertEqual(source, "rule_fallback")
            PlanValidator(self.settings, self.registry).validate(plan)
        comprehensive = self.interpreter.interpret("贵州茅台最近一年股价和研报观点")
        plan = RulePlanner(self.registry).create_plan(comprehensive, "综合分析")
        dependencies = {task.task_id: task.depends_on for task in plan.tasks}
        self.assertEqual(dependencies["indicator"], ["market"])
        self.assertEqual(dependencies["report_candidates"], [])

    def test_unknown_tool_and_cycle_are_rejected(self):
        query = self.interpreter.interpret("贵州茅台最近一个月股价走势")
        cycle = AnalysisPlan(
            query=query,
            tasks=[
                AnalysisTask(
                    task_id="market",
                    tool_name=ToolName.MARKET_QUERY,
                    arguments={
                        "stock_code": "600519",
                        "start_date": "2026-06-15",
                        "end_date": "2026-07-15",
                    },
                    depends_on=["indicator"],
                ),
                AnalysisTask(
                    task_id="indicator",
                    tool_name=ToolName.INDICATOR_CALCULATOR,
                    arguments={
                        "stock_code": "600519",
                        "start_date": "2026-06-15",
                        "end_date": "2026-07-15",
                    },
                    depends_on=["market"],
                ),
            ],
        )
        with self.assertRaisesRegex(ValueError, "cycle"):
            PlanValidator(self.settings, self.registry).validate(cycle)
        incomplete_registry = ToolRegistry()
        incomplete_registry.register(ControlledTool("market_query", "market", []))
        with self.assertRaisesRegex(ValueError, "not allowed"):
            PlanValidator(self.settings, incomplete_registry).validate(cycle)

    def test_model_plan_cannot_switch_stock(self):
        query = self.interpreter.interpret("贵州茅台最近一个月股价走势")
        switched = AnalysisPlan(
            query=query,
            tasks=[
                AnalysisTask(
                    task_id="market",
                    tool_name=ToolName.MARKET_QUERY,
                    arguments={
                        "stock_code": "300750",
                        "start_date": "2026-06-15",
                        "end_date": "2026-07-15",
                    },
                )
            ],
        )
        with self.assertRaisesRegex(ValueError, "stock differs"):
            PlanValidator(self.settings, self.registry).validate(
                switched, expected_query=query
            )

    def test_financial_plan_cannot_add_report_candidate_search(self):
        query = self.interpreter.interpret("贵州茅台最近一年营收和利润")
        plan = RulePlanner(self.registry).create_plan(query, "财务分析")
        plan = plan.model_copy(
            update={
                "tasks": [
                    *plan.tasks,
                    AnalysisTask(
                        task_id="report",
                        tool_name=ToolName.REPORT_CANDIDATE_SEARCH,
                        arguments={
                            "stock_code": "600519",
                            "query": "营收和利润",
                        },
                    ),
                ]
            }
        )
        with self.assertRaisesRegex(ValueError, "outside intent boundary"):
            PlanValidator(self.settings, self.registry).validate(plan)

    def test_execution_arguments_are_normalized_by_harness(self):
        query = self.interpreter.interpret(
            "贵州茅台最近一年股价和研报观点"
        )
        plan = RulePlanner(self.registry).create_plan(query, "旧检索词")
        modified = plan.model_copy(
            update={
                "tasks": [
                    task.model_copy(
                        update={
                            "arguments": {
                                **task.arguments,
                                "query": "模型生成的随机检索词",
                                "top_k": 9,
                            }
                        }
                    )
                    if task.tool_name == ToolName.REPORT_CANDIDATE_SEARCH
                    else task
                    for task in plan.tasks
                ]
            }
        )
        normalized = PlanValidator.normalize_for_execution(
            modified, "贵州茅台最近一年股价和研报观点"
        )
        report_task = next(
            task
            for task in normalized.tasks
            if task.tool_name == ToolName.REPORT_CANDIDATE_SEARCH
        )
        self.assertEqual(
            report_task.arguments["query"],
            "贵州茅台最近一年股价和研报观点",
        )
        self.assertEqual(report_task.arguments["top_k"], 5)

    def test_multi_stock_comparison_is_one_bounded_complete_task(self):
        question = (
            "比较600519、300750、601318从2025-08-01到2026-08-07的"
            "技术面、波动率、最大回撤与流动性"
        )
        query = self.interpreter.interpret(question)
        plan = RulePlanner(self.registry).create_plan(query, question)
        normalized = PlanValidator.normalize_for_execution(plan, question)

        validated = PlanValidator(self.settings, self.registry).validate(
            normalized,
            expected_query=query,
        )
        self.assertEqual(len(validated.tasks), 1)
        self.assertEqual(validated.tasks[0].tool_name, ToolName.STOCK_COMPARISON)
        self.assertEqual(
            validated.tasks[0].arguments["stock_codes"],
            ["600519", "300750", "601318"],
        )

    def test_market_plan_requires_complete_semantic_trajectory(self):
        query = self.interpreter.interpret("贵州茅台最近一个月股价走势")
        plan = RulePlanner(self.registry).create_plan(query, "贵州茅台最近一个月股价走势")
        broken_dependency = plan.model_copy(
            update={
                "tasks": [
                    task.model_copy(update={"depends_on": []})
                    if task.tool_name == ToolName.INDICATOR_CALCULATOR
                    else task
                    for task in plan.tasks
                ]
            }
        )
        with self.assertRaisesRegex(ValueError, "indicator task must depend"):
            PlanValidator(self.settings, self.registry).validate(broken_dependency)
        missing_indicator = plan.model_copy(update={"tasks": [plan.tasks[0]]})
        with self.assertRaisesRegex(ValueError, "missing required tools"):
            PlanValidator(self.settings, self.registry).validate(missing_indicator)


class ExecutorServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_and_dependency_order(self):
        calls: list[str] = []
        registry = ToolRegistry()
        market = ControlledTool("market_query", "market", calls, failures_before_success=1)
        indicator = ControlledTool("indicator_calculator", "market", calls)
        registry.register(market)
        registry.register(indicator)
        query = QueryInterpreter(today=date(2026, 7, 15)).interpret("贵州茅台最近一个月股价")
        plan = RulePlanner(registry).create_plan(query, "贵州茅台最近一个月股价")
        results = await PlanExecutor(registry, max_parallel=2, max_retries=2).execute(plan)
        self.assertTrue(all(result.success for result in results))
        self.assertEqual(market.attempts, 2)
        self.assertGreater(calls.index("start:indicator"), calls.index("end:market"))

    async def test_run_isolation_and_working_result(self):
        settings = Settings(max_parallel_tools=2, max_tool_retries=1)
        service = OrchestrationService(
            settings,
            controlled_registry(),
            interpreter=QueryInterpreter(today=date(2026, 7, 15)),
        )
        first, second = await asyncio.gather(
            service.run("贵州茅台最近一年股价和研报观点"),
            service.run("宁德时代最近一年股价和研报观点"),
        )
        self.assertTrue(first.success)
        self.assertTrue(second.success)
        self.assertNotEqual(first.run_id, second.run_id)
        self.assertEqual({item.subject for item in first.evidence}, {"600519"})
        self.assertEqual({item.subject for item in second.evidence}, {"300750"})
        self.assertTrue(all(item.evidence_id.startswith(f"{first.run_id}:") for item in first.evidence))
        self.assertTrue(all(item.evidence_id.startswith(f"{second.run_id}:") for item in second.evidence))
        self.assertEqual(len(first.evidence), 3)
        self.assertTrue(first.timings)
        self.assertTrue(first.semantic_alignment.passed)
        self.assertEqual(
            first.execution_metadata.business_reference_date,
            date(2026, 7, 15),
        )


if __name__ == "__main__":
    unittest.main()
