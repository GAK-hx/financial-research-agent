from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from financial_research_agent.risk.data.normalize import normalize_eastmoney_statement

CRITICAL_METRICS = {
    "revenue",
    "parent_net_profit",
    "operating_cash_flow",
    "current_assets",
    "current_liabilities",
    "total_assets",
    "total_liabilities",
}


def _expected_value(row: pd.Series, field: str) -> tuple[str, float | None]:
    if field not in row.index:
        return "not_available_from_source", None
    raw = row[field]
    if pd.isna(raw) or (isinstance(raw, str) and not raw.strip()):
        return "not_disclosed", None
    if field == "OPINION_TYPE":
        normalized = str(raw).strip().replace(" ", "")
        return "present", 0.0 if normalized in {"标准无保留意见", "无保留意见"} else 1.0
    numeric = pd.to_numeric(raw, errors="coerce")
    return ("not_disclosed", None) if pd.isna(numeric) else ("present", float(numeric))


def _equal_numeric(left: float | None, right: float | None) -> bool:
    if left is None or (isinstance(left, float) and math.isnan(left)):
        return right is None
    if right is None:
        return False
    return math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-8)


def _audit_company(company_root: Path) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    result = json.loads((company_root / "result.json").read_text(encoding="utf-8"))
    facts = pq.read_table(company_root / result["facts_path"]).to_pandas()
    facts["report_period"] = pd.to_datetime(facts["report_period"]).dt.date
    checks: list[dict[str, Any]] = []
    for statement, metadata in result["statements"].items():
        if metadata.get("status") != "success":
            continue
        raw = pq.read_table(company_root / metadata["raw_path"]).to_pandas()
        raw["__report_period"] = pd.to_datetime(raw["REPORT_DATE"], errors="coerce").dt.date
        raw_by_period = {
            row["__report_period"]: row
            for _, row in raw.drop_duplicates("__report_period", keep="first").iterrows()
        }
        statement_facts = facts[
            facts["source_record_id"].str.contains(f":{statement}:", regex=False)
        ]
        for fact in statement_facts.itertuples(index=False):
            matching = raw_by_period.get(fact.report_period)
            if matching is None:
                checks.append(
                    {
                        "issuer_id": fact.issuer_id,
                        "report_period": fact.report_period.isoformat(),
                        "metric_code": fact.metric_code,
                        "passed": False,
                        "reason": "raw_report_period_missing",
                    }
                )
                continue
            source_field = str(fact.source_record_id).rsplit(":", 1)[-1]
            expected_availability, expected_value = _expected_value(
                matching, source_field
            )
            passed = fact.availability == expected_availability and _equal_numeric(
                fact.value, expected_value
            )
            checks.append(
                {
                    "issuer_id": fact.issuer_id,
                    "report_period": fact.report_period.isoformat(),
                    "metric_code": fact.metric_code,
                    "source_field": source_field,
                    "passed": passed,
                    "reason": None if passed else "availability_or_value_mismatch",
                    "expected_availability": expected_availability,
                    "actual_availability": fact.availability,
                    "expected_value": expected_value,
                    "actual_value": None if pd.isna(fact.value) else float(fact.value),
                }
            )
    return checks, facts


def _schema_change_detected(sample_company_root: Path) -> bool:
    result = json.loads(
        (sample_company_root / "result.json").read_text(encoding="utf-8")
    )
    statement = "income"
    raw_path = sample_company_root / result["statements"][statement]["raw_path"]
    raw = pq.read_table(raw_path).to_pandas().drop(columns=["REPORT_DATE"])
    try:
        normalize_eastmoney_statement(
            raw,
            statement,
            observed_at=datetime.now(timezone.utc),
        )
    except ValueError as exc:
        return "REPORT_DATE" in str(exc)
    return False


def _completeness(facts: pd.DataFrame, applicable_issuers: set[str]) -> dict[str, Any]:
    eligible = facts[
        facts["issuer_id"].astype(str).isin(applicable_issuers)
        & facts["metric_code"].isin(CRITICAL_METRICS)
    ].copy()
    eligible["report_period"] = pd.to_datetime(eligible["report_period"]).dt.date
    annual = eligible[
        eligible["report_period"].map(lambda value: value.month == 12 and value.day == 31)
    ]
    selected = []
    for _, company in annual.groupby("issuer_id"):
        periods = sorted(set(company["report_period"]), reverse=True)[:8]
        selected.append(company[company["report_period"].isin(periods)])
    frame = pd.concat(selected, ignore_index=True) if selected else annual.iloc[0:0]
    expected = len(applicable_issuers) * 8 * len(CRITICAL_METRICS)
    key_count = len(
        frame.drop_duplicates(["issuer_id", "report_period", "metric_code"])
    )
    present = len(frame[(frame["availability"] == "present") & frame["value"].notna()])
    return {
        "expected_cells": expected,
        "mapped_cells": key_count,
        "present_valid_cells": present,
        "mapping_completeness": key_count / expected if expected else 0.0,
        "value_completeness": present / expected if expected else 0.0,
    }


def _markdown(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# 数据质量与源响应对账报告",
            "",
            f"- 公司覆盖：{report['covered_companies']}/{report['company_count']}",
            f"- 源字段对账：{report['source_reconciliation_passed']}/{report['source_reconciliation_checks']} "
            f"({report['source_reconciliation_rate']:.4%})",
            f"- 关键字段映射完整率：{report['critical_completeness']['mapping_completeness']:.4%}",
            f"- 关键字段有效值完整率：{report['critical_completeness']['value_completeness']:.4%}",
            f"- 业务主键重复：{report['business_key_duplicates']}",
            f"- 非可用状态静默带值：{report['unavailable_with_value']}",
            f"- 已知 Schema 变更发现：{report['schema_change_detected']}",
            "",
            "## 边界说明",
            "",
            "本报告完成原始 API 响应到标准化事实的逐字段程序化对账。PDF 内容质量使用公开数据集与"
            "确定性文档检查单独评价；本报告不把未覆盖事项计为通过。",
            "",
            "## 失败样例",
            "",
            "```json",
            json.dumps(report["reconciliation_failures"], ensure_ascii=False, indent=2),
            "```",
        ]
    )


def run_audit(
    root: Path,
    *,
    statement_root: Path,
    pool_file: Path,
) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    pool = json.loads(pool_file.read_text(encoding="utf-8"))
    applicable = {
        str(item["issuer_id"])
        for item in pool["entries"]
        if item.get("generic_ratio_applicable", True)
    }
    results = []
    all_facts = []
    for company_root in sorted((statement_root / "companies").iterdir()):
        result_path = company_root / "result.json"
        if not result_path.exists():
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("status") != "success" or not result.get("facts_path"):
            continue
        checks, facts = _audit_company(company_root)
        results.extend(checks)
        all_facts.append(facts)
    facts = pd.concat(all_facts, ignore_index=True) if all_facts else pd.DataFrame()
    business_keys = ["issuer_id", "report_period", "metric_code"]
    duplicates = int(facts.duplicated(business_keys).sum()) if not facts.empty else 0
    unavailable_with_value = (
        int(((facts["availability"] != "present") & facts["value"].notna()).sum())
        if not facts.empty
        else 0
    )
    passed = sum(item["passed"] for item in results)
    company_count = len(pool["entries"])
    covered = len(set(facts["issuer_id"].astype(str))) if not facts.empty else 0
    sample_company = next(
        company
        for company in sorted((statement_root / "companies").iterdir())
        if (company / "result.json").exists()
        and json.loads((company / "result.json").read_text(encoding="utf-8")).get("status")
        == "success"
    )
    report = {
        "company_count": company_count,
        "covered_companies": covered,
        "source_reconciliation_checks": len(results),
        "source_reconciliation_passed": passed,
        "source_reconciliation_rate": passed / len(results) if results else 0.0,
        "reconciliation_failure_reasons": dict(
            sorted(Counter(item["reason"] for item in results if not item["passed"]).items())
        ),
        "reconciliation_failures": [item for item in results if not item["passed"]][:50],
        "critical_completeness": _completeness(facts, applicable),
        "business_key_duplicates": duplicates,
        "unavailable_with_value": unavailable_with_value,
        "schema_change_detected": _schema_change_detected(sample_company),
        "pdf_manual_audit_status": "pending_independent_human_review",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    report["machine_gate_passed"] = bool(
        covered == company_count
        and report["source_reconciliation_rate"] >= 0.995
        and report["critical_completeness"]["mapping_completeness"] >= 0.99
        and duplicates == 0
        and unavailable_with_value == 0
        and report["schema_change_detected"]
    )
    json_path = root / "report.json"
    markdown_path = root / "report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit raw-to-standardized risk-data quality")
    parser.add_argument("--root", default="/artifacts/risk_data/quality_audit_v1")
    parser.add_argument(
        "--statement-root", default="/artifacts/risk_data/expansion_statements_v1"
    )
    parser.add_argument(
        "--pool-file",
        default="/artifacts/risk_data/expansion_pool_v1/expansion_pool_v1.json",
    )
    args = parser.parse_args()
    paths = run_audit(
        Path(args.root),
        statement_root=Path(args.statement_root),
        pool_file=Path(args.pool_file),
    )
    print(json.dumps({"json": str(paths[0]), "markdown": str(paths[1])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
