from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import Intent, QuerySpec
from financial_research_agent.providers.model import build_model_provider
from financial_research_agent.tools.analysis import (
    StockComparisonTool,
    TechnicalAnalysisTool,
)


CASES = (
    (
        "technical",
        "分析贵州茅台最近一年的技术面",
        QuerySpec(
            stock_codes=["600519"],
            start_date=date(2025, 8, 8),
            end_date=date(2026, 8, 8),
            intent=Intent.TECHNICAL,
            dimensions=["trend", "volatility"],
            analysis_domains=["market"],
        ),
    ),
    (
        "comparison",
        "比较贵州茅台和宁德时代最近一年的市场表现",
        QuerySpec(
            stock_codes=["600519", "300750"],
            start_date=date(2025, 8, 8),
            end_date=date(2026, 8, 8),
            intent=Intent.COMPREHENSIVE,
            dimensions=["comparison"],
            analysis_domains=["market"],
        ),
    ),
)


def planner_schemas() -> list[dict]:
    return [
        {
            "name": tool.definition.name,
            "description": tool.definition.description,
            "input_schema": tool.input_model.model_json_schema(),
        }
        for tool in (TechnicalAnalysisTool, StockComparisonTool)
    ]


async def main() -> None:
    settings = Settings(
        model_name="deepseek-v4-flash",
        provider_shared_rate_limit_enabled=True,
        provider_max_parallel_requests=2,
    )
    provider = build_model_provider(settings)
    schemas = planner_schemas()

    async def run_case(name: str, question: str, query: QuerySpec) -> dict:
        started = asyncio.get_running_loop().time()
        try:
            response = await provider.create_plan_response(
                question,
                query,
                schemas,
                planning_context={
                    "gate": "step4_flash_planner_only",
                    "data_sent": "question_query_spec_and_tool_schemas_only",
                },
            )
            plan = response.content
            copied_query = plan.get("query") == query.model_dump(mode="json")
            return {
                "case": name,
                "success": copied_query and bool(plan.get("tasks")),
                "query_copied_exactly": copied_query,
                "task_count": len(plan.get("tasks") or []),
                "tool_names": [
                    task.get("tool_name") for task in plan.get("tasks") or []
                ],
                "latency_ms": int(
                    (asyncio.get_running_loop().time() - started) * 1000
                ),
                "provider_request_id": response.provider_request_id,
                "usage": response.usage.model_dump(mode="json"),
                "error": None,
            }
        except Exception as exc:
            return {
                "case": name,
                "success": False,
                "latency_ms": int(
                    (asyncio.get_running_loop().time() - started) * 1000
                ),
                "error": f"{type(exc).__name__}: {exc}",
            }

    try:
        results = await asyncio.gather(
            *(run_case(*case) for case in CASES)
        )
    finally:
        await provider.aclose()
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": settings.model_name,
        "scope": "planner_only_no_local_market_or_financial_evidence",
        "passed": sum(bool(item["success"]) for item in results),
        "total": len(results),
        "results": results,
    }
    target = Path(settings.artifacts_root) / "step4"
    target.mkdir(parents=True, exist_ok=True)
    (target / "flash_gate.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Step 4 Flash Planner 并发 Gate",
        "",
        f"- 模型：`{settings.model_name}`",
        "- 范围：仅问题、QuerySpec 与 Tool Schema；不发送本地行情、财务或研报 Evidence。",
        f"- 结果：`{payload['passed']}/{payload['total']}`",
        "",
    ]
    for item in results:
        lines.extend(
            [
                f"## {item['case']}",
                "",
                "```json",
                json.dumps(item, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    (target / "FLASH_GATE.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload["passed"] != payload["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
