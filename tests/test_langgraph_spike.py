from __future__ import annotations

import asyncio
import unittest
from datetime import date, datetime, timezone
from pydantic import BaseModel

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import Evidence, SourceReference, ToolResult
from financial_research_agent.orchestration.executor import PlanExecutor
from financial_research_agent.orchestration.interpreter import QueryInterpreter
from financial_research_agent.orchestration.planner import RulePlanner, StructuredPlanner
from financial_research_agent.orchestration.registry import ToolRegistry
from financial_research_agent.orchestration.validator import PlanValidator
from financial_research_agent.tools.base import FinancialTool, ToolDefinition

try:
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from financial_research_agent.harness.spike import (
        LangGraphSpike,
        ensure_json_safe_state,
        graph_config,
        initial_spike_state,
    )

    LANGGRAPH_AVAILABLE = True
except ModuleNotFoundError:
    LANGGRAPH_AVAILABLE = False


class SpikeFinancialInput(BaseModel):
    stock_code: str
    start_date: date
    end_date: date


class CountingFinancialTool(FinancialTool):
    definition = ToolDefinition(
        name="financial_query",
        description="Controlled async financial tool for the LangGraph spike.",
        data_domain="financial",
        timeout_seconds=2,
    )
    input_model = SpikeFinancialInput

    def __init__(self, delay: float = 0.01) -> None:
        self.calls = 0
        self.delay = delay

    async def execute(self, task_id: str, arguments: SpikeFinancialInput) -> ToolResult:
        self.calls += 1
        await asyncio.sleep(self.delay)
        evidence = Evidence(
            evidence_id=f"financial-{arguments.stock_code}",
            evidence_type="financial",
            subject=arguments.stock_code,
            statement="controlled financial evidence",
            data={"report_date": "2025-12-31"},
            source=SourceReference(
                source_type="iceberg",
                locator=f"iceberg://spike/{arguments.stock_code}",
                observed_at=datetime.now(timezone.utc),
            ),
        )
        return ToolResult(
            task_id=task_id,
            success=True,
            evidence=[evidence],
            latency_ms=1,
        )


@unittest.skipUnless(LANGGRAPH_AVAILABLE, "LangGraph is isolated to the harness profile")
class LangGraphSpikeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings = Settings(max_evidence=10, max_tool_retries=0)
        self.tool = CountingFinancialTool()
        self.registry = ToolRegistry()
        self.registry.register(self.tool)
        planner = StructuredPlanner(
            self.registry,
            RulePlanner(self.registry),
            provider=None,
        )
        self.spike = LangGraphSpike(
            settings=self.settings,
            interpreter=QueryInterpreter(today=date(2026, 7, 24)),
            planner=planner,
            validator=PlanValidator(self.settings, self.registry),
            executor=PlanExecutor(self.registry, max_parallel=2, max_retries=0),
        )

    async def test_graph_reuses_pydantic_models_and_state_is_json_safe(self) -> None:
        graph = self.spike.build(InMemorySaver())
        initial = initial_spike_state("贵州茅台最近三年营收和利润", "spike-json")
        result = await graph.ainvoke(initial, graph_config(initial["thread_id"]))

        ensure_json_safe_state(result)
        self.assertEqual(result["stage"], "completed")
        self.assertEqual(result["planner_source"], "rule_fallback")
        self.assertEqual(len(result["tool_results"]), 1)
        self.assertEqual(len(result["evidence"]), 1)
        self.assertFalse(result["report_preview"]["production_report"])
        self.assertEqual(self.tool.calls, 1)

    async def test_interrupt_resume_defers_tool_and_does_not_repeat_after_completion(self) -> None:
        graph = self.spike.build(InMemorySaver(), require_tool_approval=True)
        initial = initial_spike_state("贵州茅台最近三年营收和利润", "spike-resume")
        config = graph_config(initial["thread_id"])

        paused = await graph.ainvoke(initial, config)
        self.assertIn("__interrupt__", paused)
        self.assertEqual(self.tool.calls, 0)
        snapshot = await graph.aget_state(config)
        ensure_json_safe_state(snapshot.values)

        resumed = await graph.ainvoke(Command(resume=True), config)
        self.assertEqual(resumed["stage"], "completed")
        self.assertEqual(self.tool.calls, 1)

        final_read = await graph.ainvoke(None, config)
        self.assertEqual(final_read["stage"], "completed")
        self.assertEqual(self.tool.calls, 1)

    async def test_interrupt_rejection_is_a_terminal_state_without_tool_call(self) -> None:
        graph = self.spike.build(InMemorySaver(), require_tool_approval=True)
        initial = initial_spike_state("贵州茅台最近三年营收和利润", "spike-reject")
        config = graph_config(initial["thread_id"])

        await graph.ainvoke(initial, config)
        rejected = await graph.ainvoke(Command(resume=False), config)

        self.assertEqual(rejected["stage"], "rejected")
        self.assertEqual(rejected["errors"][0]["code"], "INTERRUPT_REJECTED")
        self.assertEqual(self.tool.calls, 0)
        ensure_json_safe_state(rejected)

    async def test_async_tool_keeps_event_loop_responsive(self) -> None:
        self.tool.delay = 0.05
        graph = self.spike.build(InMemorySaver())
        initial = initial_spike_state("贵州茅台最近三年营收和利润", "spike-async")

        run = asyncio.create_task(graph.ainvoke(initial, graph_config(initial["thread_id"])))
        await asyncio.sleep(0.01)
        self.assertFalse(run.done())
        result = await run

        self.assertEqual(result["stage"], "completed")

    def test_non_json_object_is_rejected_before_checkpoint(self) -> None:
        with self.assertRaisesRegex(ValueError, "STATE_SERIALIZATION_ERROR"):
            ensure_json_safe_state({"client": object()})


if __name__ == "__main__":
    unittest.main()
