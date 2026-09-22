from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from pyiceberg.io.pyarrow import schema_to_pyarrow

from financial_research_agent.config import Settings
from financial_research_agent.data_management.models import DataTier, IngestionBatch, SourceMetadata
from financial_research_agent.data_management.storage import BatchMetadataStore, RawBatchStore
from financial_research_agent.repositories.iceberg import IcebergAdmin, IcebergRepository
from financial_research_agent.risk.disclosures import normalize_disclosures
from financial_research_agent.risk.models import DisclosureEvent, IssuerPoolEntry
from financial_research_agent.risk.pools import load_correctness_pool
from financial_research_agent.risk.schema import (
    DISCLOSURE_EVENT_SCHEMA,
    DISCLOSURE_EVENT_TABLE,
    TABLE_SCHEMAS,
)
from financial_research_agent.risk.source_audit import _call_with_retry, _frame_digest

MAPPING_VERSION = "cninfo-disclosure-v2"
DISCLOSURE_QUERIES: dict[str, dict[str, str]] = {
    "annual_reports": {"category": "年报", "keyword": ""},
    "corrections": {"category": "补充更正", "keyword": ""},
    "risk_alerts": {"category": "风险提示", "keyword": ""},
    "audit_reports": {"category": "中介报告", "keyword": "审计"},
    "inquiries": {"category": "", "keyword": "问询函"},
    "forecast_revisions": {"category": "业绩预告", "keyword": "修正"},
}


def _event_rows(events: list[DisclosureEvent]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        item = event.model_dump()
        item["query_tags_json"] = json.dumps(item.pop("query_tags"), ensure_ascii=False)
        item["event_types_json"] = json.dumps(
            [value.value for value in item.pop("event_types")], ensure_ascii=False
        )
        rows.append(item)
    return rows


def _write_company(
    entry: IssuerPoolEntry,
    root: Path,
    *,
    start_date: str,
    end_date: str,
    retries: int,
    initial_backoff_seconds: float,
    call_timeout_seconds: float,
) -> dict[str, Any]:
    company_root = root / "companies" / entry.issuer_id
    result_path = company_root / "result.json"
    existing: dict[str, Any] | None = None
    if result_path.exists():
        existing = json.loads(result_path.read_text(encoding="utf-8"))
        if existing.get("status") == "success" and existing.get("mapping_version") == MAPPING_VERSION:
            return existing
    company_root.mkdir(parents=True, exist_ok=True)
    raw_store = RawBatchStore(company_root)
    observed_at = (
        datetime.fromisoformat(existing["observed_at"])
        if existing and existing.get("observed_at")
        else datetime.now(timezone.utc)
    )
    frames: dict[str, Any] = {}
    query_results: dict[str, Any] = {}
    can_reprocess = bool(
        existing
        and existing.get("status") == "success"
        and len(existing.get("query_results", {})) == len(DISCLOSURE_QUERIES)
        and all(
            item.get("status") == "success"
            and item.get("raw_path")
            and (company_root / item["raw_path"]).exists()
            for item in existing.get("query_results", {}).values()
        )
    )
    if can_reprocess and existing is not None:
        query_results = existing["query_results"]
        for query_tag, item in query_results.items():
            frames[query_tag] = pq.read_table(company_root / item["raw_path"]).to_pandas()
    else:
        observed_at = datetime.now(timezone.utc)
        for query_tag, filters in DISCLOSURE_QUERIES.items():
            parameters = {
                "symbol": entry.issuer_id,
                "market": "沪深京",
                "category": filters["category"],
                "keyword": filters["keyword"],
                "start_date": start_date,
                "end_date": end_date,
            }
            frame, errors = _call_with_retry(
                "stock_zh_a_disclosure_report_cninfo",
                parameters,
                retries=retries,
                initial_backoff_seconds=initial_backoff_seconds,
                call_timeout_seconds=call_timeout_seconds,
            )
            if frame is None:
                query_results[query_tag] = {
                    "status": "failed",
                    "parameters": parameters,
                    "errors": errors,
                }
                continue
            frames[query_tag] = frame
            raw_path = raw_store.write(
                f"risk_cninfo_{query_tag}",
                f"{entry.issuer_id}-{query_tag}-{observed_at:%Y%m%dT%H%M%SZ}",
                pa.Table.from_pandas(frame, preserve_index=False),
            )
            query_results[query_tag] = {
                "status": "success",
                "parameters": parameters,
                "rows": len(frame),
                "columns": [str(column) for column in frame.columns],
                "content_sha256": _frame_digest(frame),
                "raw_path": str(raw_path.relative_to(company_root)),
                "retry_errors": errors,
            }

    events, rejected = normalize_disclosures(frames, observed_at=observed_at)
    events_path = company_root / "disclosure_events.parquet"
    if events:
        pq.write_table(pa.Table.from_pylist(_event_rows(events)), events_path, compression="zstd")
    rejected_path = company_root / "rejected.json"
    rejected_path.write_text(json.dumps(rejected, ensure_ascii=False, indent=2), encoding="utf-8")
    type_counts = Counter(
        event_type.value for event in events for event_type in event.event_types
    )
    raw_rows = sum(item.get("rows", 0) for item in query_results.values())
    successful_queries = sum(item["status"] == "success" for item in query_results.values())
    result = {
        "issuer_id": entry.issuer_id,
        "issuer_name": entry.issuer_name,
        "mapping_version": MAPPING_VERSION,
        "status": "success" if successful_queries == len(DISCLOSURE_QUERIES) else "warning",
        "query_results": query_results,
        "successful_queries": successful_queries,
        "query_count": len(DISCLOSURE_QUERIES),
        "raw_row_count": raw_rows,
        "deduplicated_event_count": len(events),
        "duplicate_query_hits": raw_rows - len(events),
        "event_type_counts": dict(sorted(type_counts.items())),
        "rejected_count": len(rejected),
        "requires_document_review_count": sum(event.requires_document_review for event in events),
        "coverage_passed": successful_queries == len(DISCLOSURE_QUERIES) and bool(events),
        "observed_at": observed_at.isoformat(),
        "events_path": str(events_path.relative_to(company_root)) if events else None,
        "rejected_path": str(rejected_path.relative_to(company_root)),
    }
    temporary = result_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, result_path)
    return result


def _write_iceberg(root: Path, results: list[dict[str, Any]]) -> dict[str, Any] | None:
    event_paths = [
        root / "companies" / item["issuer_id"] / item["events_path"]
        for item in results
        if item.get("events_path")
    ]
    if not event_paths:
        return None
    digest = hashlib.sha256()
    for path in sorted(event_paths):
        digest.update(path.read_bytes())
    input_fingerprint = digest.hexdigest()
    iceberg_root = root / "iceberg" / input_fingerprint[:16]
    iceberg_root.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        iceberg_catalog_uri=f"sqlite:///{iceberg_root / 'catalog.db'}",
        iceberg_warehouse=f"file://{iceberg_root / 'warehouse'}",
        lake_root=str(root / "lake"),
    )
    admin = IcebergAdmin(settings)
    repository = IcebergRepository(settings)
    admin.bootstrap_namespaces()
    for table_name, schema in TABLE_SCHEMAS.items():
        if not repository.table_exists(table_name):
            admin.create_table(table_name, schema)
    table = repository.catalog.load_table(DISCLOSURE_EVENT_TABLE)
    existing_snapshot = table.current_snapshot()
    if existing_snapshot is not None:
        return {
            "table": DISCLOSURE_EVENT_TABLE,
            "rows": table.scan().to_arrow().num_rows,
            "snapshot_id": existing_snapshot.snapshot_id,
            "input_fingerprint": input_fingerprint,
            "catalog": str(iceberg_root / "catalog.db"),
            "warehouse": str(iceberg_root / "warehouse"),
            "reused": True,
        }
    combined = pa.concat_tables(
        [pq.read_table(path) for path in event_paths], promote_options="default"
    )
    combined = combined.select([field.name for field in DISCLOSURE_EVENT_SCHEMA.fields])
    combined = combined.cast(schema_to_pyarrow(DISCLOSURE_EVENT_SCHEMA), safe=False)
    ingestion = IngestionBatch(
        batch_id=f"disclosure-pool-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}",
        dataset="disclosure_event",
        tier=DataTier.STANDARDIZED,
        source=SourceMetadata(
            source="akshare_cninfo_disclosure",
            endpoint="stock_zh_a_disclosure_report_cninfo",
            mapping_version=MAPPING_VERSION,
            parameters={"pool_id": "issuer_risk_correctness_pool", "company_count": len(results)},
        ),
        input_rows=combined.num_rows,
        output_rows=combined.num_rows,
    )
    completed = repository.append(
        DISCLOSURE_EVENT_TABLE,
        combined,
        ingestion,
        BatchMetadataStore(settings.lake_root),
    )
    return {
        "table": DISCLOSURE_EVENT_TABLE,
        "rows": combined.num_rows,
        "snapshot_id": completed.snapshot_id,
        "input_fingerprint": input_fingerprint,
        "catalog": str(iceberg_root / "catalog.db"),
        "warehouse": str(iceberg_root / "warehouse"),
        "reused": False,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Step 01 公告事件池采集报告",
        "",
        f"- 日期范围：`{report['start_date']}`—`{report['end_date']}`",
        f"- 公司覆盖：{report['covered_companies']}/{report['company_count']}",
        f"- 去重后事件：{report['deduplicated_event_count']}",
        f"- 状态：`{report['status']}`",
        "- 说明：标题分类仅生成复核候选，全部事件均保留 `requires_document_review=true`。",
        "",
        "| 代码 | 公司 | 查询成功 | 原始命中 | 去重事件 | 拒绝 | 状态 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for item in report["companies"]:
        lines.append(
            f"| {item['issuer_id']} | {item['issuer_name']} | "
            f"{item['successful_queries']}/{item['query_count']} | {item['raw_row_count']} | "
            f"{item['deduplicated_event_count']} | {item['rejected_count']} | {item['status']} |"
        )
    lines.extend(["", "## 事件类型分布", "", "```json"])
    lines.append(json.dumps(report["event_type_counts"], ensure_ascii=False, indent=2))
    lines.extend(["```", "", "## Iceberg", "", "```json"])
    lines.append(json.dumps(report.get("iceberg"), ensure_ascii=False, indent=2))
    lines.extend(["```", "", "## 失败明细", ""])
    failures = [item for item in report["companies"] if item["status"] != "success"]
    if not failures:
        lines.append("无。")
    for item in failures:
        lines.extend(
            [
                f"### {item['issuer_id']} {item['issuer_name']}",
                "",
                "```json",
                json.dumps(item.get("query_results", {}), ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def run_pool(
    root: Path,
    *,
    start_date: str,
    end_date: str,
    workers: int,
    retries: int,
    initial_backoff_seconds: float,
    call_timeout_seconds: float,
    limit: int | None,
) -> tuple[Path, Path]:
    import akshare as ak

    pool = load_correctness_pool()
    entries = pool.entries[:limit] if limit else pool.entries
    root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _write_company,
                entry,
                root,
                start_date=start_date,
                end_date=end_date,
                retries=retries,
                initial_backoff_seconds=initial_backoff_seconds,
                call_timeout_seconds=call_timeout_seconds,
            ): entry
            for entry in entries
        }
        for future in as_completed(futures):
            entry = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "issuer_id": entry.issuer_id,
                    "issuer_name": entry.issuer_name,
                    "status": "failed",
                    "query_results": {},
                    "successful_queries": 0,
                    "query_count": len(DISCLOSURE_QUERIES),
                    "raw_row_count": 0,
                    "deduplicated_event_count": 0,
                    "event_type_counts": {},
                    "rejected_count": 0,
                    "coverage_passed": False,
                    "events_path": None,
                    "fatal_error": f"{type(exc).__name__}:{exc}",
                }
            results.append(result)
            print(
                json.dumps(
                    {
                        "issuer_id": result["issuer_id"],
                        "status": result["status"],
                        "events": result.get("deduplicated_event_count", 0),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    results.sort(key=lambda item: item["issuer_id"])
    iceberg = _write_iceberg(root, results)
    covered = sum(item.get("coverage_passed") is True for item in results)
    type_counts = Counter()
    for item in results:
        type_counts.update(item.get("event_type_counts", {}))
    report = {
        "pool_id": pool.pool_id,
        "pool_version": pool.version,
        "akshare_version": getattr(ak, "__version__", "unknown"),
        "start_date": start_date,
        "end_date": end_date,
        "company_count": len(results),
        "covered_companies": covered,
        "raw_row_count": sum(item.get("raw_row_count", 0) for item in results),
        "deduplicated_event_count": sum(
            item.get("deduplicated_event_count", 0) for item in results
        ),
        "event_type_counts": dict(sorted(type_counts.items())),
        "status": "success" if covered >= min(19, len(results)) else "warning",
        "companies": results,
        "iceberg": iceberg,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    json_path = root / "report.json"
    markdown_path = root / "report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect the frozen disclosure-event pool")
    parser.add_argument("--root", default="artifacts/phase5_step01/disclosure_pool_v1")
    parser.add_argument("--start-date", default="20180101")
    parser.add_argument("--end-date", default="20260907")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--initial-backoff-seconds", type=float, default=5.0)
    parser.add_argument("--call-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if not 1 <= args.workers <= 3:
        raise ValueError("workers must be between 1 and 3")
    paths = run_pool(
        Path(args.root),
        start_date=args.start_date,
        end_date=args.end_date,
        workers=args.workers,
        retries=args.retries,
        initial_backoff_seconds=args.initial_backoff_seconds,
        call_timeout_seconds=args.call_timeout_seconds,
        limit=args.limit,
    )
    print(json.dumps({"json": str(paths[0]), "markdown": str(paths[1])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
