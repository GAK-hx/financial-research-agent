from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime, timezone

from pydantic import BaseModel

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import Evidence, SourceReference, ToolResult
from financial_research_agent.harness.spike import (
    LangGraphSpike,
    graph_config,
    initial_spike_state,
)
from financial_research_agent.orchestration.executor import PlanExecutor
from financial_research_agent.orchestration.interpreter import QueryInterpreter
from financial_research_agent.orchestration.planner import RulePlanner, StructuredPlanner
from financial_research_agent.orchestration.registry import ToolRegistry
from financial_research_agent.orchestration.validator import PlanValidator
from financial_research_agent.persistence.checkpoint import postgres_checkpointer
from financial_research_agent.tools.base import FinancialTool, ToolDefinition


class AuditFinancialInput(BaseModel):
    stock_code: str
    start_date: date | None = None
    end_date: date | None = None


class AuditFinancialTool(FinancialTool):
    definition = ToolDefinition(
        name="financial_query",
        description="Controlled persistence recovery audit tool.",
        data_domain="financial",
        timeout_seconds=5,
    )
    input_model = AuditFinancialInput

    def __init__(self) -> None:
        self.calls = 0

    async def execute(
        self, task_id: str, arguments: AuditFinancialInput
    ) -> ToolResult:
        self.calls += 1
        return ToolResult(
            task_id=task_id,
            success=True,
            evidence=[
                Evidence(
                    evidence_id="persistence-audit",
                    evidence_type="financial",
                    subject=arguments.stock_code,
                    statement="persistence recovery audit evidence",
                    data={"audit": True},
                    source=SourceReference(
                        source_type="iceberg",
                        locator=f"iceberg://persistence-audit/{arguments.stock_code}",
                        observed_at=datetime.now(timezone.utc),
                    ),
                )
            ],
            latency_ms=0,
        )


def build_spike(settings: Settings, tool: AuditFinancialTool) -> LangGraphSpike:
    registry = ToolRegistry()
    registry.register(tool)
    return LangGraphSpike(
        settings=settings,
        interpreter=QueryInterpreter(today=settings.evaluation_reference_date),
        planner=StructuredPlanner(registry, RulePlanner(registry), provider=None),
        validator=PlanValidator(settings, registry),
        executor=PlanExecutor(registry, max_parallel=2, max_retries=0),
    )


async def interrupt(thread_id: str) -> dict:
    settings = Settings()
    if settings.checkpoint_backend != "postgres":
        raise ValueError("audit requires CHECKPOINT_BACKEND=postgres")
    tool = AuditFinancialTool()
    spike = build_spike(settings, tool)
    initial = initial_spike_state(
        "贵州茅台最近三年营收和利润", run_id=thread_id
    )
    async with postgres_checkpointer(settings) as saver:
        graph = spike.build(saver, require_tool_approval=True)
        result = await graph.ainvoke(initial, graph_config(thread_id))
    return {
        "thread_id": thread_id,
        "interrupted": "__interrupt__" in result,
        "tool_calls": tool.calls,
    }


async def resume(thread_id: str, approved: bool) -> dict:
    from langgraph.types import Command

    settings = Settings()
    if settings.checkpoint_backend != "postgres":
        raise ValueError("audit requires CHECKPOINT_BACKEND=postgres")
    tool = AuditFinancialTool()
    spike = build_spike(settings, tool)
    async with postgres_checkpointer(settings) as saver:
        graph = spike.build(saver, require_tool_approval=True)
        result = await graph.ainvoke(
            Command(resume=approved), graph_config(thread_id)
        )
    return {
        "thread_id": thread_id,
        "stage": result.get("stage"),
        "tool_calls": tool.calls,
        "evidence_count": len(result.get("evidence", [])),
    }


async def inspect_database() -> dict:
    from sqlalchemy import text

    from financial_research_agent.persistence.database import create_business_engine

    settings = Settings()
    engine = create_business_engine(settings)
    try:
        async with engine.connect() as connection:
            size = await connection.scalar(
                text("SELECT pg_database_size(current_database())")
            )
            rows = await connection.execute(
                text(
                    "SELECT relname, pg_total_relation_size(relid) "
                    "FROM pg_stat_user_tables ORDER BY relname"
                )
            )
            tables = {row[0]: int(row[1]) for row in rows}
        return {"database_bytes": int(size), "table_bytes": tables}
    finally:
        await engine.dispose()


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="Step 03 persistence recovery audit.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    interrupt_parser = subparsers.add_parser("interrupt")
    interrupt_parser.add_argument("--thread-id", required=True)
    resume_parser = subparsers.add_parser("resume")
    resume_parser.add_argument("--thread-id", required=True)
    resume_parser.add_argument("--reject", action="store_true")
    subparsers.add_parser("inspect")
    args = parser.parse_args()

    if args.command == "interrupt":
        result = await interrupt(args.thread_id)
    elif args.command == "resume":
        result = await resume(args.thread_id, not args.reject)
    else:
        result = await inspect_database()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main_async())
