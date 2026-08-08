from __future__ import annotations

import asyncio
import json

from financial_research_agent.config import get_settings
from financial_research_agent.orchestration.factory import build_orchestration_service


CASES = {
    "financial": "分析宁德时代最近三年的营收、利润和盈利能力",
    "report": "总结贵州茅台最新研报中的机构观点",
    "comprehensive": "综合分析贵州茅台最近一年的股价表现、趋势指标和机构观点",
}


async def run() -> None:
    service = build_orchestration_service(get_settings())
    output: dict[str, dict] = {}
    for name, question in CASES.items():
        result = await service.run(question)
        output[name] = {
            "run_id": result.run_id,
            "success": result.success,
            "planner_source": result.planner_source,
            "tasks": [
                {
                    "task_id": task.task_id,
                    "tool": task.tool_name,
                    "depends_on": task.depends_on,
                }
                for task in (result.plan.tasks if result.plan else [])
            ],
            "tool_success": all(item.success for item in result.tool_results),
            "evidence_count": len(result.evidence),
            "errors": result.errors,
            "timings_ms": {item.stage: item.duration_ms for item in result.timings},
        }
        if not result.success or result.planner_source != "model":
            raise RuntimeError(f"model planner audit failed: {name}")
    print(json.dumps(output, ensure_ascii=False, indent=2))


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
