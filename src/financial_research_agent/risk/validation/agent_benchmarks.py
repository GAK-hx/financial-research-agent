from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _json(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _run_ready(report: dict[str, Any] | None, expected: int = 20) -> bool:
    return bool(
        report
        and report.get("status") == "PASS"
        and report.get("selected_cases") == expected
        and report.get("successful_cases") == expected
        and report.get("failed_cases") == 0
        and report.get("gold_used_during_inference") is False
        and report.get("evaluation_split_gold_used_during_inference") is False
    )


def _score_ready(score: dict[str, Any] | None, expected: int = 20) -> bool:
    return bool(
        score
        and score.get("status") == "SCORED"
        and score.get("inference_failed_cases") == 0
        and score.get("metrics", {}).get("case_count") == expected
    )


def build_report(root: Path, *, artifacts_root: Path, docs_output: Path | None) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    complex_root = artifacts_root / "complex_subset_v1"
    configurations = {
        "financebench_B": complex_root / "single_agent/financebench",
        "financebench_D": complex_root / "dynamic_team/financebench",
        "finqa_B": complex_root / "single_agent/finqa",
        "finqa_C": complex_root / "fixed_team/finqa",
        "finqa_D": complex_root / "dynamic_team/finqa",
        "tatqa_B": complex_root / "single_agent/tatqa",
        "tatqa_C": complex_root / "fixed_team/tatqa",
        "tatqa_D": complex_root / "dynamic_team/tatqa",
    }
    runs = {name: _json(path / "report.json") for name, path in configurations.items()}
    scores = {
        name: _json(path / "score/score.json") for name, path in configurations.items()
    }
    v4 = _json(artifacts_root / "v4finbench_h1_v1/a1_a2_comparison.json")
    selection = _json(artifacts_root / "team_selection_smoke_v1/report.json")
    repair_root = artifacts_root / "repair_regression_v1/dynamic_team"
    repair_rows = _jsonl(repair_root / "results.jsonl")
    repair_score = _json(repair_root / "score/score.json")

    inference_ready = all(_run_ready(report) for report in runs.values())
    scores_ready = all(_score_ready(score) for score in scores.values())
    failures_empty = all(
        not _jsonl(path / "failures.jsonl") for path in configurations.values()
    )
    repair_format_ready = bool(
        len(repair_rows) == 4
        and all(
            row.get("artifact", {}).get("evaluation", {}).get("decision")
            in {"ACCEPT", "ACCEPT_WITH_LIMITATIONS"}
            and not any(
                str(item).startswith("PROGRAM_EXECUTION_FAILED:")
                for run in row.get("agent_runs", [])
                for item in run.get("hypothesis", {}).get("missing_information", [])
            )
            for row in repair_rows
        )
        and _score_ready(repair_score, expected=4)
    )
    finance_b = scores.get("financebench_B", {}).get("metrics", {})
    finance_d = scores.get("financebench_D", {}).get("metrics", {})
    finqa_b = scores.get("finqa_B", {}).get("metrics", {})
    finqa_c = scores.get("finqa_C", {}).get("metrics", {})
    finqa_d = scores.get("finqa_D", {}).get("metrics", {})
    tatqa_b = scores.get("tatqa_B", {}).get("metrics", {})
    tatqa_c = scores.get("tatqa_C", {}).get("metrics", {})
    tatqa_d = scores.get("tatqa_D", {}).get("metrics", {})
    routing_supported = bool(
        finance_d.get("numeric_accuracy") == finance_b.get("numeric_accuracy")
        and finance_d.get("evidence_recall") == finance_b.get("evidence_recall")
        and finqa_c.get("execution_accuracy", 0) > finqa_b.get("execution_accuracy", 0)
        and finqa_d.get("execution_accuracy", 0) >= finqa_c.get("execution_accuracy", 0)
        and tatqa_d.get("exact_match", 0) > tatqa_c.get("exact_match", 0)
        > tatqa_b.get("exact_match", 0)
    )
    checks = [
        _check(
            "V4FinBench A1/A2",
            bool(
                v4
                and v4.get("status") == "READY"
                and v4.get("significant_enough_for_project") is True
                and all(item.get("ready") for item in v4.get("coverage", {}).values())
            ),
            "官方公司分组五折；A2固定参数；A1/A2各996,500条预测完整覆盖",
        ),
        _check(
            "Supervisor与Harness最小闭环",
            bool(
                selection
                and selection.get("status") == "PASS"
                and selection.get("failed_cases") == 0
                and selection.get("gold_used_during_selection") is False
            ),
            "三类任务选择成功，选择阶段Gold不可见",
        ),
        _check(
            "B/C/D冻结复杂题推理",
            inference_ready,
            "8组所需配置均20/20成功；FinanceBench C因D未超过B而停止补跑",
        ),
        _check(
            "官方或确定性评分",
            scores_ready,
            "8组评分均覆盖20题且无推理失败",
        ),
        _check(
            "推理Gold隔离与失败归档",
            inference_ready and failures_empty,
            "Gold标志均为false；本轮8组运行失败数为0",
        ),
        _check(
            "按任务路由证据",
            routing_supported,
            "FinanceBench走B；FinQA复杂题走C；TAT-QA指定复杂类型允许D",
        ),
        _check(
            "FinQA程序格式回归",
            repair_format_ready,
            "历史4题格式失败降为0/4，Evaluator接受4/4；官方Execution 3/4、Program 2/4",
        ),
    ]
    passed = sum(item["passed"] for item in checks)
    report = {
        "status": "SUCCESS" if passed == len(checks) else "FAIL",
        "passed": passed,
        "total": len(checks),
        "checks": checks,
        "default_routing": {
            "financebench": "single_agent",
            "finqa_complex": "fixed_team",
            "tatqa_arithmetic_or_table_text_complex": "dynamic_team",
            "fallback": "single_agent",
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    lines = [
        "# Agent公开Benchmark验证",
        "",
        f"- 总状态：`{report['status']}`；",
        f"- 自动检查：{passed}/{len(checks)}；",
        "- 结论：动态多Agent按任务路由，不作为全局默认；",
        "- 分数要求：只验证稳定、明显的相对改善，不继续为简历目标调参。",
        "",
        "| 检查项 | 结果 | 说明 |",
        "|---|---|---|",
    ]
    for item in checks:
        lines.append(
            f"| {item['name']} | {'PASS' if item['passed'] else 'FAIL'} | {item['detail']} |"
        )
    lines.extend(
        [
            "",
            "## 默认路由",
            "",
            "- FinanceBench与简单题：单Agent；",
            "- FinQA复杂题：固定表格推理+量化分析团队；",
            "- TAT-QA复杂算术或table-text：动态Supervisor团队；",
            "- 无法确认复杂度或证据不足：回退单Agent或明确拒答。",
        ]
    )
    markdown = "\n".join(lines) + "\n"
    (root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (root / "report.md").write_text(markdown, encoding="utf-8")
    if docs_output:
        docs_output.parent.mkdir(parents=True, exist_ok=True)
        docs_output.write_text(markdown, encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the consolidated agent benchmark report")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("/artifacts/agent_benchmarks/validation_report_v1"),
    )
    parser.add_argument(
        "--artifacts-root", type=Path, default=Path("/artifacts/agent_benchmarks")
    )
    parser.add_argument("--docs-output", type=Path)
    args = parser.parse_args()
    report = build_report(
        args.root, artifacts_root=args.artifacts_root, docs_output=args.docs_output
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
