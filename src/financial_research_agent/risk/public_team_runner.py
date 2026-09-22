from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any, Literal

from financial_research_agent.config import get_settings
from financial_research_agent.providers.model import build_model_provider
from financial_research_agent.risk.financebench_index import FinanceBenchPageStore
from financial_research_agent.risk.finqa_program_skill import FinQAProgramSkill
from financial_research_agent.risk.public_benchmark_runner import (
    _input_path,
    _filter_cases_by_manifest,
    _load_registry,
    _prepare_case_payload,
    _read_jsonl,
)
from financial_research_agent.risk.team_runtime import BenchmarkTeamRuntime
from financial_research_agent.risk.team_supervisor import FixedTeamSupervisor


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


def _failure_markdown(
    *, benchmark: str, model: str, mode: str, failures: list[dict[str, Any]]
) -> str:
    lines = [
        "# 多 Agent 团队失败记录",
        "",
        f"- Benchmark：`{benchmark}`",
        f"- 模型：`{model}`",
        f"- 配置：`{mode}`",
        f"- 失败数：{len(failures)}",
        "",
    ]
    if not failures:
        lines.append("本轮无失败案例。")
    for failure in failures:
        lines.extend(
            [
                f"## {failure['case_id']}",
                "",
                f"- 错误：`{failure['error_type']}` — {failure['error']}",
                f"- 耗时：{failure['latency_seconds']} 秒",
                "",
                "```text",
                (failure.get("raw_output") or "无原始输出").replace("```", "'''"),
                "```",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


async def run_dynamic_team(
    *,
    benchmark_root: Path,
    corpus_registry_path: Path,
    index_path: Path,
    output_root: Path,
    benchmark: Literal["financebench", "finqa", "tatqa"],
    split: str,
    limit: int | None,
    case_id: str | None,
    resume: bool,
    retry_failures: bool,
    finqa_skill_index_path: Path,
    team_mode: Literal["dynamic", "fixed"] = "dynamic",
    case_manifest_path: Path | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    cases = _read_jsonl(_input_path(benchmark_root, benchmark, split))
    cases = _filter_cases_by_manifest(
        cases,
        manifest_path=case_manifest_path,
        benchmark=benchmark,
        split=split,
    )
    if case_id:
        cases = [case for case in cases if str(case["case_id"]) == case_id]
    if limit is not None:
        cases = cases[:limit]
    if not cases:
        raise ValueError("no benchmark cases selected")

    registry = _load_registry(corpus_registry_path) if benchmark == "financebench" else {}
    page_store = (
        FinanceBenchPageStore(index_path) if benchmark == "financebench" else None
    )
    program_skill = (
        FinQAProgramSkill(finqa_skill_index_path)
        if benchmark == "finqa" and finqa_skill_index_path.exists()
        else None
    )
    provider = build_model_provider(settings)
    runtime = BenchmarkTeamRuntime(
        provider,
        supervisor=FixedTeamSupervisor() if team_mode == "fixed" else None,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    results_path = output_root / "results.jsonl"
    failures_path = output_root / "failures.jsonl"
    results = _read_jsonl(results_path) if resume and results_path.exists() else []
    failures = _read_jsonl(failures_path) if resume and failures_path.exists() else []
    previous_failure_count = 0
    if resume and retry_failures and failures:
        previous_failure_count = len(failures)
        (output_root / "failures.previous.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in failures),
            encoding="utf-8",
        )
        failures = []
        failures_path.write_text("", encoding="utf-8")
    if not resume:
        results_path.write_text("", encoding="utf-8")
        failures_path.write_text("", encoding="utf-8")
    completed_ids = {str(row["case_id"]) for row in [*results, *failures]}
    try:
        for case in cases:
            if str(case["case_id"]) in completed_ids:
                continue
            started = time.perf_counter()
            try:
                controlled_context, queries, preparation_usage = await _prepare_case_payload(
                    case=case,
                    mode="single_agent" if benchmark == "financebench" else "direct",
                    provider=provider,
                    page_store=page_store,
                    document_registry=registry,
                )
                program_examples: list[dict[str, Any]] = []
                if program_skill is not None:
                    program_examples = program_skill.search(
                        question=str(case["question"]),
                        case_id=str(case["case_id"]),
                        top_k=3,
                    )
                    controlled_context = {
                        **controlled_context,
                        "finqa_program_skill": {
                            "source_split": "train",
                            "examples": program_examples,
                            "usage_policy": (
                                "Syntax and operation-pattern guidance only; examples are not "
                                "evidence for the current answer."
                            ),
                        },
                    }
                state = await runtime.run(
                    benchmark=benchmark,
                    case_id=str(case["case_id"]),
                    question=str(case["question"]),
                    controlled_context=controlled_context,
                    task_metadata=_task_metadata(case),
                    preparation_tool_calls=len(queries),
                    preparation_usage=preparation_usage,
                )
                result = {
                    "benchmark": benchmark,
                    "split": split,
                    "case_id": case["case_id"],
                    "mode": f"{team_mode}_team",
                    "model": settings.model_name,
                    "prediction": state["final_answer"],
                    "team_plan": state["team_plan"],
                    "artifact": state["artifact"],
                    "agent_runs": state["agent_runs"],
                    "evaluations": state["evaluations"],
                    "node_trace": state["node_trace"],
                    "search_queries": queries,
                    "retrieval_coverage": controlled_context.get("retrieval_coverage", {}),
                    "public_train_skill_used": bool(program_examples),
                    "latency_seconds": round(time.perf_counter() - started, 3),
                }
                results.append(result)
                with results_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(result, ensure_ascii=False) + "\n")
            except Exception as exc:  # noqa: BLE001 - preserve failure evidence
                failure = {
                        "benchmark": benchmark,
                        "split": split,
                        "case_id": case.get("case_id"),
                        "mode": f"{team_mode}_team",
                        "model": settings.model_name,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "raw_output": str(getattr(exc, "raw_output", "")),
                        "latency_seconds": round(time.perf_counter() - started, 3),
                    }
                failures.append(failure)
                with failures_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(failure, ensure_ascii=False) + "\n")
    finally:
        await provider.aclose()

    (output_root / "failures.md").write_text(
        _failure_markdown(
            benchmark=benchmark,
            model=settings.model_name,
            mode=f"{team_mode}_team",
            failures=failures,
        ),
        encoding="utf-8",
    )
    report = {
        "status": "PASS" if results and not failures else "PARTIAL" if results else "FAIL",
        "benchmark": benchmark,
        "split": split,
        "mode": f"{team_mode}_team",
        "model": settings.model_name,
        "selected_cases": len(cases),
        "successful_cases": len(results),
        "failed_cases": len(failures),
        "retried_previous_failures": previous_failure_count,
        "gold_used_during_inference": False,
        "evaluation_split_gold_used_during_inference": False,
        "public_train_skill_used": program_skill is not None,
        "results_path": str(results_path),
        "failures_path": str(failures_path),
    }
    (output_root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run dynamic public-benchmark Agent team")
    parser.add_argument(
        "--benchmark-root", default="/artifacts/phase5_step01/public_benchmarks_v1"
    )
    parser.add_argument(
        "--corpus-registry",
        default="/artifacts/phase5_step02/financebench_corpus_v1/document_registry.jsonl",
    )
    parser.add_argument(
        "--index",
        default="/artifacts/phase5_step02/financebench_index_v1/financebench_pages.sqlite",
    )
    parser.add_argument("--output-root", required=True)
    parser.add_argument(
        "--benchmark", choices=("financebench", "finqa", "tatqa"), required=True
    )
    parser.add_argument("--split", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--case-id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-failures", action="store_true")
    parser.add_argument(
        "--team-mode", choices=("dynamic", "fixed"), default="dynamic"
    )
    parser.add_argument(
        "--finqa-skill-index",
        default="/artifacts/phase5_step02/finqa_program_skill_v1/examples.sqlite",
    )
    parser.add_argument("--case-manifest")
    args = parser.parse_args()
    report = asyncio.run(
        run_dynamic_team(
            benchmark_root=Path(args.benchmark_root),
            corpus_registry_path=Path(args.corpus_registry),
            index_path=Path(args.index),
            output_root=Path(args.output_root),
            benchmark=args.benchmark,
            split=args.split,
            limit=args.limit,
            case_id=args.case_id,
            resume=args.resume,
            retry_failures=args.retry_failures,
            finqa_skill_index_path=Path(args.finqa_skill_index),
            team_mode=args.team_mode,
            case_manifest_path=(Path(args.case_manifest) if args.case_manifest else None),
        )
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
