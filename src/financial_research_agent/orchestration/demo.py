from __future__ import annotations

import argparse
import asyncio
import json

from financial_research_agent.config import get_settings
from financial_research_agent.orchestration.factory import build_orchestration_service


async def run(question: str) -> None:
    settings = get_settings()
    service = build_orchestration_service(settings)
    result = await service.run(question)
    payload = {
        "run_id": result.run_id,
        "success": result.success,
        "stage": result.stage,
        "planner_source": result.planner_source,
        "query": result.query.model_dump(mode="json") if result.query else None,
        "tasks": [
            {
                "task_id": task.task_id,
                "tool": task.tool_name,
                "depends_on": task.depends_on,
            }
            for task in (result.plan.tasks if result.plan else [])
        ],
        "tool_results": [
            {
                "task_id": item.task_id,
                "success": item.success,
                "error_code": item.error_code,
                "evidence_count": len(item.evidence),
                "latency_ms": item.latency_ms,
            }
            for item in result.tool_results
        ],
        "evidence": [
            {
                "evidence_id": item.evidence_id,
                "type": item.evidence_type,
                "subject": item.subject,
                "locator": item.source.locator,
            }
            for item in result.evidence
        ],
        "timings": [item.model_dump(mode="json") for item in result.timings],
        "errors": result.errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not result.success:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the step-seven orchestration demo")
    parser.add_argument(
        "question",
        nargs="?",
        default="分析贵州茅台最近一年的股价表现和研报观点",
    )
    args = parser.parse_args()
    asyncio.run(run(args.question))


if __name__ == "__main__":
    main()
