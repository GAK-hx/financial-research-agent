from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def _read(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _check(name: str, passed: bool, *, detail: str, blocking: str = "machine") -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "blocking": blocking,
        "detail": detail,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 风险数据底座验证",
        "",
        f"- 总状态：`{report['status']}`",
        f"- 自动检查：{report['passed']}/{report['total']}",
        "",
        "| 检查项 | 类型 | 结果 | 说明 |",
        "|---|---|---|---|",
    ]
    for item in report["checks"]:
        lines.append(
            f"| {item['name']} | automatic | "
            f"{'PASS' if item['passed'] else 'PENDING/FAIL'} | {item['detail']} |"
        )
    lines.extend(
        [
            "",
            "## 判定规则",
            "",
            "- `SUCCESS`：数据底座和公开 Benchmark 接入全部通过；",
            "- `FAIL`：至少一项自动检查未通过；",
            "- 自有公司数据只用于业务演示和性能测试，不建立人工标签评测。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_report(root: Path, *, artifacts_root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    statements = _read(artifacts_root / "expansion_statements_v1" / "report.json")
    features = _read(artifacts_root / "features_v1" / "report.json")
    quality = _read(artifacts_root / "quality_audit_v1" / "report.json")
    documents = _read(artifacts_root / "document_audit_v1" / "report.json")
    public_benchmarks = _read(artifacts_root / "public_benchmarks_v1" / "manifest.json")
    public_scorers = _read(artifacts_root / "public_benchmark_scorers_v1" / "report.json")

    covered = int(statements.get("covered_companies", 0)) if statements else 0
    statement_total = int(statements.get("company_count", 0)) if statements else 0
    completeness = quality.get("critical_completeness", {}) if quality else {}
    checks = [
        _check(
            "100家公司三表池",
            covered == 100 and statement_total == 100,
            detail=f"覆盖 {covered}/{statement_total}",
        ),
        _check(
            "原始事实快照幂等",
            bool(
                statements
                and statements.get("iceberg", {}).get("reused")
                and statements["iceberg"].get("rows", 0) > 0
            ),
            detail="相同输入重跑需复用事实表 Iceberg Snapshot",
        ),
        _check(
            "原始响应逐字段对账",
            bool(
                quality
                and quality.get("machine_gate_passed")
                and quality.get("source_reconciliation_rate", 0) >= 0.995
                and completeness.get("value_completeness", 0) >= 0.99
                and quality.get("business_key_duplicates") == 0
                and quality.get("unavailable_with_value") == 0
                and quality.get("schema_change_detected") is True
            ),
            detail=(
                f"对账率 {quality.get('source_reconciliation_rate', 0):.4%}，"
                f"关键值完整率 {completeness.get('value_completeness', 0):.4%}"
                if quality
                else "报告缺失"
            ),
        ),
        _check(
            "Point-in-Time 输出泄漏",
            bool(features and features.get("pit_output_leak_count") == 0),
            detail=(
                f"泄漏 {features.get('pit_output_leak_count')}"
                if features
                else "报告缺失"
            ),
        ),
        _check(
            "特征快照可复现",
            bool(
                features
                and features.get("iceberg")
                and all(
                    table.get("reused")
                    for table in features["iceberg"].get("tables", {}).values()
                )
            ),
            detail="相同输入重跑需复用全部 Iceberg Snapshot",
        ),
        _check(
            "公开 Benchmark 官方数据适配",
            bool(
                public_benchmarks
                and public_benchmarks.get("status") == "READY"
                and set(public_benchmarks.get("datasets", {}))
                == {"financebench", "finqa", "tatqa"}
                and public_benchmarks.get("total_case_count", 0) > 0
                and all(
                    item.get("case_count", 0) > 0
                    for item in public_benchmarks.get("datasets", {}).values()
                )
            ),
            detail=(
                "FinanceBench/FinQA/TAT-QA，"
                f"共 {public_benchmarks.get('total_case_count')} 例"
                if public_benchmarks
                else "报告缺失"
            ),
        ),
        _check(
            "公开 Benchmark 评分入口",
            bool(
                public_scorers
                and public_scorers.get("status") == "PASS"
                and set(public_scorers.get("results", {}))
                == {"financebench", "finqa", "tatqa"}
                and all(
                    item.get("status") == "PASS"
                    for item in public_scorers.get("results", {}).values()
                )
            ),
            detail="FinQA/TAT-QA官方评分脚本及FinanceBench Gold Schema最小验证",
        ),
        _check(
            "官方 PDF 机器抽检",
            bool(documents and documents.get("status") == "MACHINE_PASS"),
            detail=(
                f"{documents.get('machine_passed_documents')}/"
                f"{documents.get('planned_documents')}"
                if documents
                else "报告缺失"
            ),
        ),
    ]
    passed = sum(item["passed"] for item in checks)
    status = "SUCCESS" if passed == len(checks) else "FAIL"
    report = {
        "status": status,
        "passed": passed,
        "total": len(checks),
        "checks": checks,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    json_path = root / "report.json"
    markdown_path = root / "report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the consolidated risk-data validation report")
    parser.add_argument("--root", default="/artifacts/risk_data/validation_report_v1")
    parser.add_argument("--artifacts-root", default="/artifacts/risk_data")
    args = parser.parse_args()
    paths = build_report(Path(args.root), artifacts_root=Path(args.artifacts_root))
    print(json.dumps({"json": str(paths[0]), "markdown": str(paths[1])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
