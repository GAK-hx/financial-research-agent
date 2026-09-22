from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
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
from financial_research_agent.risk.domain.models import IssuerPoolEntry
from financial_research_agent.risk.data.normalize import MAPPING_VERSION, normalize_eastmoney_statement
from financial_research_agent.risk.data.pools import load_correctness_pool
from financial_research_agent.risk.data.schema import DWD_FACT_SCHEMA, DWD_FACT_TABLE, TABLE_SCHEMAS
from financial_research_agent.risk.data.source_audit import Probe, _call_with_retry, _frame_digest

STATEMENT_PROBES = {
    "income": "stock_profit_sheet_by_report_em",
    "balance": "stock_balance_sheet_by_report_em",
    "cash_flow": "stock_cash_flow_sheet_by_report_em",
}
CORE_METRICS = {
    "revenue",
    "parent_net_profit",
    "operating_cash_flow",
    "current_assets",
    "current_liabilities",
    "cash_and_equivalents",
    "short_term_borrowings",
    "accounts_receivable",
    "inventory",
    "goodwill",
    "total_assets",
    "total_liabilities",
    "audit_opinion_flag",
}


def _symbol(stock_code: str) -> str:
    return f"{'SH' if stock_code.startswith('6') else 'SZ'}{stock_code}"


def _fact_rows(facts) -> list[dict[str, Any]]:
    rows = []
    for fact in facts:
        row = fact.model_dump()
        row["availability"] = fact.availability.value
        row["source_snapshot_id"] = row.pop("snapshot_id")
        row["mapping_version"] = MAPPING_VERSION
        row["quality_passed"] = True
        rows.append(row)
    return rows


def _write_company(
    entry: IssuerPoolEntry,
    root: Path,
    *,
    retries: int,
    initial_backoff_seconds: float,
    call_timeout_seconds: float,
    akshare_version: str,
    legacy_checkpoint_akshare_version: str | None,
) -> dict[str, Any]:
    company_root = root / "companies" / entry.issuer_id
    result_path = company_root / "result.json"
    existing: dict[str, Any] = {}
    if result_path.exists():
        existing = json.loads(result_path.read_text(encoding="utf-8"))
        if existing.get("status") == "success":
            return existing
    company_root.mkdir(parents=True, exist_ok=True)
    raw_store = RawBatchStore(company_root)
    current_observed_at = datetime.now(timezone.utc)
    all_facts = []
    all_rejected: list[dict[str, Any]] = []
    statements: dict[str, Any] = {}
    statement_versions: set[str] = set()
    observation_times: list[datetime] = []
    for statement, endpoint_name in STATEMENT_PROBES.items():
        previous = existing.get("statements", {}).get(statement, {})
        previous_raw = company_root / previous.get("raw_path", "__missing__")
        reused = previous.get("status") == "success" and previous_raw.is_file()
        if reused:
            frame = pq.read_table(previous_raw).to_pandas()
            errors = list(previous.get("retry_errors", []))
            statement_observed_at = datetime.fromisoformat(
                previous.get("observed_at")
                or existing.get("observed_at")
                or current_observed_at.isoformat()
            )
            statement_version = str(
                previous.get("akshare_version")
                or existing.get("akshare_version")
                or legacy_checkpoint_akshare_version
                or "unknown"
            )
            raw_path = previous_raw
        else:
            probe = Probe(
                name=f"eastmoney_{statement}",
                endpoint=endpoint_name,
                parameters={"symbol": _symbol(entry.issuer_id)},
            )
            frame, new_errors = _call_with_retry(
                probe.endpoint,
                probe.parameters,
                retries=retries,
                initial_backoff_seconds=initial_backoff_seconds,
                call_timeout_seconds=call_timeout_seconds,
            )
            errors = list(previous.get("errors", [])) + new_errors
            statement_observed_at = current_observed_at
            statement_version = akshare_version
        if frame is None:
            statements[statement] = {"status": "failed", "errors": errors}
            continue
        digest = _frame_digest(frame)
        if not reused:
            batch_id = (
                f"{entry.issuer_id}-{statement}-{statement_observed_at:%Y%m%dT%H%M%SZ}"
            )
            raw_path = raw_store.write(
                f"risk_eastmoney_{statement}",
                batch_id,
                pa.Table.from_pandas(frame, preserve_index=False),
            )
        facts, rejected = normalize_eastmoney_statement(
            frame,
            statement,
            observed_at=statement_observed_at,
        )
        all_facts.extend(facts)
        all_rejected.extend([{"statement": statement, **item} for item in rejected])
        statement_versions.add(statement_version)
        observation_times.append(statement_observed_at)
        statements[statement] = {
            "status": "success",
            "rows": len(frame),
            "columns": len(frame.columns),
            "content_sha256": digest,
            "raw_path": str(raw_path.relative_to(company_root)),
            "normalised_facts": len(facts),
            "rejected_rows": len(rejected),
            "retry_errors": errors,
            "observed_at": statement_observed_at.isoformat(),
            "akshare_version": statement_version,
            "checkpoint_reused": reused,
        }

    facts_path = company_root / "risk_facts.parquet"
    if all_facts:
        pq.write_table(pa.Table.from_pylist(_fact_rows(all_facts)), facts_path, compression="zstd")
    rejected_path = company_root / "rejected.json"
    rejected_path.write_text(
        json.dumps(all_rejected, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    present = [fact for fact in all_facts if fact.availability.value == "present"]
    report_periods = sorted({fact.report_period for fact in all_facts})
    present_codes = {fact.metric_code for fact in present}
    result = {
        "issuer_id": entry.issuer_id,
        "issuer_name": entry.issuer_name,
        "industry_group": entry.industry_group,
        "business_type": entry.business_type,
        "generic_ratio_applicable": entry.generic_ratio_applicable,
        "akshare_version": "+".join(sorted(statement_versions)) or akshare_version,
        "status": (
            "success"
            if all(item.get("status") == "success" for item in statements.values())
            and len(statements) == len(STATEMENT_PROBES)
            else "warning"
        ),
        "statements": statements,
        "fact_count": len(all_facts),
        "present_fact_count": len(present),
        "report_period_count": len(report_periods),
        "min_report_period": report_periods[0].isoformat() if report_periods else None,
        "max_report_period": report_periods[-1].isoformat() if report_periods else None,
        "core_metrics_present": sorted(CORE_METRICS & present_codes),
        "core_metrics_missing": sorted(CORE_METRICS - present_codes),
        "coverage_passed": (
            len(report_periods) >= 8
            and all(item.get("status") == "success" for item in statements.values())
        ),
        "observed_at": max(observation_times, default=current_observed_at).isoformat(),
        "facts_path": str(facts_path.relative_to(company_root)) if all_facts else None,
        "rejected_path": str(rejected_path.relative_to(company_root)),
    }
    temporary = result_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, result_path)
    return result


def _write_iceberg(
    root: Path, results: list[dict[str, Any]], *, pool_id: str
) -> dict[str, Any] | None:
    fact_paths = [
        root / "companies" / item["issuer_id"] / item["facts_path"]
        for item in results
        if item.get("facts_path")
    ]
    if not fact_paths:
        return None
    digest = hashlib.sha256()
    for path in sorted(fact_paths):
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
    existing_table = repository.catalog.load_table(DWD_FACT_TABLE)
    existing_snapshot = existing_table.current_snapshot()
    if existing_snapshot is not None:
        return {
            "table": DWD_FACT_TABLE,
            "rows": existing_table.scan().to_arrow().num_rows,
            "snapshot_id": existing_snapshot.snapshot_id,
            "input_fingerprint": input_fingerprint,
            "catalog": str(iceberg_root / "catalog.db"),
            "warehouse": str(iceberg_root / "warehouse"),
            "reused": True,
        }
    combined = pa.concat_tables([pq.read_table(path) for path in fact_paths], promote_options="default")
    combined = combined.select([field.name for field in DWD_FACT_SCHEMA.fields])
    combined = combined.cast(schema_to_pyarrow(DWD_FACT_SCHEMA), safe=False)
    batch_id = f"risk-pool-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    ingestion = IngestionBatch(
        batch_id=batch_id,
        dataset="risk_fact_pit",
        tier=DataTier.STANDARDIZED,
        source=SourceMetadata(
            source="akshare_eastmoney_financial_statement",
            endpoint="three_statement_pool",
            mapping_version=MAPPING_VERSION,
            parameters={"pool_id": pool_id, "company_count": len(results)},
        ),
        input_rows=combined.num_rows,
        output_rows=combined.num_rows,
    )
    completed = repository.append(
        DWD_FACT_TABLE,
        combined,
        ingestion,
        BatchMetadataStore(settings.lake_root),
    )
    return {
        "table": DWD_FACT_TABLE,
        "rows": combined.num_rows,
        "snapshot_id": completed.snapshot_id,
        "input_fingerprint": input_fingerprint,
        "catalog": str(iceberg_root / "catalog.db"),
        "warehouse": str(iceberg_root / "warehouse"),
        "reused": False,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 正确性小池采集报告",
        "",
        f"- Pool：`{report['pool_id']}@{report['pool_version']}`",
        f"- AkShare 版本分布：`{json.dumps(report['akshare_versions'], ensure_ascii=False)}`",
        f"- 公司覆盖：{report['covered_companies']}/{report['company_count']}",
        f"- 状态：`{report['status']}`",
        "",
        "| 代码 | 公司 | 类型 | 三表状态 | 报告期数 | 缺失核心指标 |",
        "|---|---|---|---:|---:|---|",
    ]
    for item in report["companies"]:
        lines.append(
            f"| {item['issuer_id']} | {item['issuer_name']} | {item['business_type']} | "
            f"{item['status']} | {item['report_period_count']} | "
            f"{', '.join(item['core_metrics_missing']) or '-'} |"
        )
    lines.extend(["", "## Iceberg", "", "```json"])
    lines.append(json.dumps(report.get("iceberg"), ensure_ascii=False, indent=2))
    lines.extend(["```", "", "## 失败与警告", ""])
    warned = [item for item in report["companies"] if item["status"] != "success"]
    if not warned:
        lines.append("无。")
    for item in warned:
        lines.extend(
            [
                f"### {item['issuer_id']} {item['issuer_name']}",
                "",
                "```json",
                json.dumps(item["statements"], ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def run_pool(
    root: Path,
    *,
    workers: int,
    retries: int,
    initial_backoff_seconds: float,
    call_timeout_seconds: float,
    limit: int | None,
    pool_file: Path | None = None,
    seed_root: Path | None = None,
    legacy_checkpoint_akshare_version: str | None = None,
) -> tuple[Path, Path]:
    import akshare as ak

    if pool_file is None:
        pool = load_correctness_pool()
        pool_id = pool.pool_id
        pool_version = pool.version
        pool_frozen_at = pool.frozen_at.isoformat()
        all_entries = pool.entries
    else:
        payload = json.loads(pool_file.read_text(encoding="utf-8"))
        pool_id = str(payload["pool_id"])
        pool_version = str(payload["version"])
        pool_frozen_at = str(payload["frozen_at"])
        all_entries = [IssuerPoolEntry.model_validate(item) for item in payload["entries"]]
    entries = all_entries[:limit] if limit else all_entries
    root.mkdir(parents=True, exist_ok=True)
    seeded_issuers: list[str] = []
    if seed_root is not None:
        for entry in entries:
            source = seed_root / "companies" / entry.issuer_id
            destination = root / "companies" / entry.issuer_id
            source_result = source / "result.json"
            if destination.exists() or not source_result.exists():
                continue
            result = json.loads(source_result.read_text(encoding="utf-8"))
            if result.get("status") != "success":
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination)
            seeded_issuers.append(entry.issuer_id)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _write_company,
                entry,
                root,
                retries=retries,
                initial_backoff_seconds=initial_backoff_seconds,
                call_timeout_seconds=call_timeout_seconds,
                akshare_version=getattr(ak, "__version__", "unknown"),
                legacy_checkpoint_akshare_version=legacy_checkpoint_akshare_version,
            ): entry
            for entry in entries
        }
        for future in as_completed(futures):
            entry = futures[future]
            try:
                result = future.result()
                if "akshare_version" not in result:
                    result["akshare_version"] = legacy_checkpoint_akshare_version or "unknown"
                    result_path = root / "companies" / entry.issuer_id / "result.json"
                    temporary = result_path.with_suffix(".json.tmp")
                    temporary.write_text(
                        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    os.replace(temporary, result_path)
            except Exception as exc:
                result = {
                    "issuer_id": entry.issuer_id,
                    "issuer_name": entry.issuer_name,
                    "business_type": entry.business_type,
                    "status": "failed",
                    "statements": {},
                    "fact_count": 0,
                    "report_period_count": 0,
                    "core_metrics_missing": sorted(CORE_METRICS),
                    "coverage_passed": False,
                    "fatal_error": f"{type(exc).__name__}:{exc}",
                    "facts_path": None,
                    "akshare_version": getattr(ak, "__version__", "unknown"),
                }
            results.append(result)
            print(
                json.dumps(
                    {
                        "issuer_id": result["issuer_id"],
                        "status": result["status"],
                        "report_period_count": result.get("report_period_count", 0),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    results.sort(key=lambda item: item["issuer_id"])
    iceberg = _write_iceberg(root, results, pool_id=pool_id)
    covered = sum(item.get("coverage_passed") is True for item in results)
    akshare_versions = Counter(item["akshare_version"] for item in results)
    required_coverage = 19 if len(results) == 20 else len(results)
    report = {
        "pool_id": pool_id,
        "pool_version": pool_version,
        "pool_frozen_at": pool_frozen_at,
        "akshare_version": getattr(ak, "__version__", "unknown"),
        "akshare_versions": dict(sorted(akshare_versions.items())),
        "company_count": len(results),
        "covered_companies": covered,
        "coverage_rate": round(covered / len(results), 4) if results else 0.0,
        "required_coverage": required_coverage,
        "seeded_issuers": seeded_issuers,
        "status": "success" if covered >= required_coverage else "warning",
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
    parser = argparse.ArgumentParser(description="Collect the frozen financial-risk correctness pool")
    parser.add_argument("--root", default="artifacts/risk_data/correctness_pool_v1")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--initial-backoff-seconds", type=float, default=5.0)
    parser.add_argument("--call-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--pool-file", type=Path)
    parser.add_argument("--seed-root", type=Path)
    parser.add_argument("--legacy-checkpoint-akshare-version")
    args = parser.parse_args()
    if not 1 <= args.workers <= 3:
        raise ValueError("workers must be between 1 and 3")
    paths = run_pool(
        Path(args.root),
        workers=args.workers,
        retries=args.retries,
        initial_backoff_seconds=args.initial_backoff_seconds,
        call_timeout_seconds=args.call_timeout_seconds,
        limit=args.limit,
        pool_file=args.pool_file,
        seed_root=args.seed_root,
        legacy_checkpoint_akshare_version=args.legacy_checkpoint_akshare_version,
    )
    print(json.dumps({"json": str(paths[0]), "markdown": str(paths[1])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
