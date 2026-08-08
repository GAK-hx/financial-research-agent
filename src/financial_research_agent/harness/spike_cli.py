from __future__ import annotations

import argparse
import asyncio
import json

from langgraph.checkpoint.memory import InMemorySaver

from financial_research_agent.config import Settings
from financial_research_agent.harness.spike import (
    LangGraphSpike,
    ensure_json_safe_state,
    graph_config,
    initial_spike_state,
)
from financial_research_agent.orchestration.executor import PlanExecutor
from financial_research_agent.orchestration.interpreter import QueryInterpreter
from financial_research_agent.orchestration.planner import RulePlanner, StructuredPlanner
from financial_research_agent.orchestration.registry import ToolRegistry
from financial_research_agent.orchestration.validator import PlanValidator
from financial_research_agent.providers.model import OpenAICompatibleProvider
from financial_research_agent.tools.financial import FinancialQueryTool


async def run_live_spike(question: str, *, require_model: bool) -> dict:
    settings = Settings()
    registry = ToolRegistry()
    registry.register(FinancialQueryTool(settings))
    planner = StructuredPlanner(
        registry,
        RulePlanner(registry),
        OpenAICompatibleProvider(settings),
    )
    spike = LangGraphSpike(
        settings=settings,
        interpreter=QueryInterpreter(),
        planner=planner,
        validator=PlanValidator(settings, registry),
        executor=PlanExecutor(
            registry,
            max_parallel=settings.max_parallel_tools,
            max_retries=settings.max_tool_retries,
        ),
    )
    graph = spike.build(InMemorySaver())
    initial = initial_spike_state(question)
    result = await graph.ainvoke(initial, graph_config(initial["thread_id"]))
    ensure_json_safe_state(result)
    if require_model and result.get("planner_source") != "model":
        raise RuntimeError("DeepSeek planner did not return a valid AnalysisPlan")
    return {
        "run_id": result["run_id"],
        "stage": result["stage"],
        "planner_source": result["planner_source"],
        "tool_success": [item["success"] for item in result["tool_results"]],
        "evidence_count": len(result["evidence"]),
        "report_preview": result["report_preview"],
        "errors": result["errors"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the isolated LangGraph phase-two spike.")
    parser.add_argument(
        "--question",
        default="贵州茅台最近三年营收和利润",
    )
    parser.add_argument(
        "--require-model",
        action="store_true",
        help="Fail instead of accepting the existing deterministic planner fallback.",
    )
    args = parser.parse_args()
    result = asyncio.run(run_live_spike(args.question, require_model=args.require_model))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
