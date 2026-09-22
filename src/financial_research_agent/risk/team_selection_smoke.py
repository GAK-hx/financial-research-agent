from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from financial_research_agent.config import get_settings
from financial_research_agent.providers.model import build_model_provider
from financial_research_agent.risk.team_supervisor import TeamSupervisor


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _task_metadata(case: dict[str, Any]) -> dict[str, Any]:
    context = case.get("context") or {}
    preview_parts: list[str] = []
    for item in context.get("pre_text") or []:
        preview_parts.append(str(item))
    for item in context.get("post_text") or []:
        preview_parts.append(str(item))
    for item in context.get("paragraphs") or []:
        preview_parts.append(str(item.get("text") or ""))
    table = context.get("table") or []
    table_rows = table.get("table", []) if isinstance(table, dict) else table
    if table_rows:
        preview_parts.append(json.dumps(table_rows[:4], ensure_ascii=False))
    return {
        "document_count": len(case.get("document_refs") or []),
        "has_table": bool(context.get("table")),
        "has_text": bool(
            context.get("pre_text")
            or context.get("post_text")
            or context.get("paragraphs")
        ),
        "context_preview": "\n".join(preview_parts)[:2400],
    }


async def run_smoke(benchmark_root: Path, output_root: Path) -> dict[str, Any]:
    selections = [
        ("financebench", "open_source"),
        ("finqa", "dev"),
        ("tatqa", "dev"),
    ]
    provider = build_model_provider(get_settings())
    supervisor = TeamSupervisor(provider)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    try:
        for benchmark, split in selections:
            case = _read_jsonl(
                benchmark_root / "inputs" / benchmark / f"{split}.jsonl"
            )[0]
            try:
                selected = await supervisor.select_team(
                    benchmark=benchmark,
                    case_id=str(case["case_id"]),
                    question=str(case["question"]),
                    task_metadata=_task_metadata(case),
                )
                results.append(selected.model_dump(mode="json"))
            except Exception as exc:  # noqa: BLE001 - persist the feasibility failure
                failures.append(
                    {
                        "benchmark": benchmark,
                        "case_id": case["case_id"],
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "raw_output": str(getattr(exc, "raw_output", "")),
                    }
                )
    finally:
        await provider.aclose()

    output_root.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "PASS" if len(results) == len(selections) else "PARTIAL",
        "model": get_settings().model_name,
        "gold_used_during_selection": False,
        "selected_cases": len(selections),
        "successful_cases": len(results),
        "failed_cases": len(failures),
        "results": results,
        "failures": failures,
    }
    (output_root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# 动态团队选择最小检查",
        "",
        f"- 状态：`{report['status']}`",
        f"- 模型：`{report['model']}`",
        "- Supervisor 未读取 Gold 答案、Gold Evidence 或 Gold Program。",
        "",
    ]
    for item in results:
        plan = item["plan"]
        lines.extend(
            [
                f"## {plan['benchmark']} / {plan['case_id']}",
                "",
                f"- 任务：{plan['task_summary']}",
                "- 团队：" + ", ".join(agent["role"] for agent in plan["agents"]),
                f"- Tool 预算：{sum(agent['max_tool_calls'] for agent in plan['agents'])} / {plan['total_tool_call_budget']}",
                f"- Token 预算：{sum(agent['max_tokens'] for agent in plan['agents'])} / {plan['total_token_budget']}",
                "",
            ]
        )
    for failure in failures:
        lines.extend(
            [
                f"## 失败：{failure['benchmark']} / {failure['case_id']}",
                "",
                f"- {failure['error_type']}：{failure['error']}",
                "",
                "```text",
                failure["raw_output"].replace("```", "'''") or "无原始输出",
                "```",
                "",
            ]
        )
    (output_root / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test dynamic Agent team selection")
    parser.add_argument(
        "--benchmark-root",
        default="/artifacts/phase5_step01/public_benchmarks_v1",
    )
    parser.add_argument(
        "--output-root",
        default="/artifacts/phase5_step02/team_selection_smoke_v1",
    )
    args = parser.parse_args()
    report = asyncio.run(run_smoke(Path(args.benchmark_root), Path(args.output_root)))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
