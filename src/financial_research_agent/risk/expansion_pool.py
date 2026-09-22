from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pandas as pd

from financial_research_agent.risk.source_audit import _call_with_retry, _frame_digest

POOL_ID = "issuer_risk_expansion_pool"
POOL_VERSION = "v1"
SOURCE_INDEX = "000300"
KNOWN_INSURERS = {"中国平安", "中国人保", "新华保险", "中国太保"}


def _business_type(name: str) -> tuple[str, bool]:
    if "银行" in name:
        return "bank", False
    if "保险" in name or name in KNOWN_INSURERS:
        return "insurance", False
    if "证券" in name:
        return "securities", False
    return "non_financial", True


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Step 01 扩展池冻结报告",
        "",
        f"- Pool：`{report['pool_id']}@{report['version']}`",
        f"- 来源指数：`{report['source_index_code']} {report['source_index_name']}`",
        f"- 成分生效日期：`{report['constituent_date']}`",
        f"- 冻结公司数：{report['company_count']}",
        f"- 通用工商企业比率适用：{report['generic_ratio_applicable_count']}",
        f"- 通用工商企业比率不适用：{report['generic_ratio_not_applicable_count']}",
        "",
        "选择规则：将源响应按六位证券代码升序排序，固定取前100家公司；规则在财务接口覆盖检查前执行。",
        "",
        "| 序号 | 代码 | 名称 | 交易所 | 通用比率适用 |",
        "|---:|---|---|---|---:|",
    ]
    for index, item in enumerate(report["entries"], start=1):
        lines.append(
            f"| {index} | {item['issuer_id']} | {item['issuer_name']} | "
            f"{item['exchange']} | {item['generic_ratio_applicable']} |"
        )
    return "\n".join(lines)


def build_pool(
    root: Path,
    *,
    company_count: int,
    retries: int,
    initial_backoff_seconds: float,
    call_timeout_seconds: float,
    refresh_from_raw: bool = False,
) -> tuple[Path, Path]:
    if company_count != 100:
        raise ValueError("IssuerRiskBench v1 expansion pool must freeze exactly 100 companies")
    root.mkdir(parents=True, exist_ok=True)
    pool_path = root / "expansion_pool_v1.json"
    report_path = root / "report.md"
    if pool_path.exists() and report_path.exists() and not refresh_from_raw:
        return pool_path, report_path
    raw_path = root / "csi300_constituents_raw.parquet"
    if raw_path.exists():
        frame = pq.read_table(raw_path).to_pandas()
    else:
        frame, errors = _call_with_retry(
            "index_stock_cons_csindex",
            {"symbol": SOURCE_INDEX},
            retries=retries,
            initial_backoff_seconds=initial_backoff_seconds,
            call_timeout_seconds=call_timeout_seconds,
        )
        if frame is None:
            failure_path = root / "failure.json"
            failure_path.write_text(
                json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            raise RuntimeError(f"cannot freeze expansion pool; see {failure_path}")
        pq.write_table(
            pa.Table.from_pandas(frame, preserve_index=False), raw_path, compression="zstd"
        )
    required = {"日期", "指数代码", "指数名称", "成分券代码", "成分券名称", "交易所"}
    if missing := required - set(frame.columns):
        raise ValueError(f"index constituent response missing columns: {sorted(missing)}")
    selected = frame.assign(
        成分券代码=frame["成分券代码"].astype(str).str.zfill(6)
    ).sort_values("成分券代码", kind="stable").head(company_count)
    entries = []
    for row in selected.to_dict(orient="records"):
        name = str(row["成分券名称"]).strip()
        business_type, applicable = _business_type(name)
        entries.append(
            {
                "issuer_id": str(row["成分券代码"]),
                "issuer_name": name,
                "exchange": str(row["交易所"]),
                "industry_group": "未分类（沪深300成分）",
                "business_type": business_type,
                "generic_ratio_applicable": applicable,
                "selection_rank": len(entries) + 1,
                "selection_reason": "按冻结中证300成分响应的证券代码升序选入扩展池",
            }
        )
    constituent_dates = sorted(
        {
            value.date().isoformat()
            for value in pd.to_datetime(selected["日期"], errors="coerce")
            if not pd.isna(value)
        }
    )
    if not constituent_dates:
        raise ValueError("index constituent response contains no valid constituent date")
    report = {
        "pool_id": POOL_ID,
        "version": POOL_VERSION,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "selection_policy": "Sort the frozen CSI 300 source response by security code and take the first 100 before checking statement coverage.",
        "source_index_code": SOURCE_INDEX,
        "source_index_name": str(selected.iloc[0]["指数名称"]),
        "constituent_date": constituent_dates[-1],
        "source_endpoint": "akshare.index_stock_cons_csindex",
        "source_response_sha256": _frame_digest(frame),
        "raw_path": str(raw_path.relative_to(root)),
        "company_count": len(entries),
        "generic_ratio_applicable_count": sum(
            item["generic_ratio_applicable"] for item in entries
        ),
        "generic_ratio_not_applicable_count": sum(
            not item["generic_ratio_applicable"] for item in entries
        ),
        "entries": entries,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    report["pool_sha256"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    pool_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(_markdown(report), encoding="utf-8")
    return pool_path, report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze the 100-company expansion pool")
    parser.add_argument("--root", default="artifacts/phase5_step01/expansion_pool_v1")
    parser.add_argument("--company-count", type=int, default=100)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--initial-backoff-seconds", type=float, default=5.0)
    parser.add_argument("--call-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--refresh-from-raw", action="store_true")
    args = parser.parse_args()
    paths = build_pool(
        Path(args.root),
        company_count=args.company_count,
        retries=args.retries,
        initial_backoff_seconds=args.initial_backoff_seconds,
        call_timeout_seconds=args.call_timeout_seconds,
        refresh_from_raw=args.refresh_from_raw,
    )
    print(json.dumps({"pool": str(paths[0]), "report": str(paths[1])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
