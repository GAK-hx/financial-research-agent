from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pyiceberg.io.pyarrow import schema_to_pyarrow

from financial_research_agent.config import Settings
from financial_research_agent.data_management.models import DataTier, IngestionBatch, SourceMetadata
from financial_research_agent.data_management.storage import BatchMetadataStore
from financial_research_agent.repositories.iceberg import IcebergAdmin, IcebergRepository
from financial_research_agent.risk.domain.models import DataAvailability, RiskCategory, RiskStatus
from financial_research_agent.risk.domain.registry import RiskMetricRegistry
from financial_research_agent.risk.data.schema import (
    ADS_CANDIDATE_SCHEMA,
    ADS_CANDIDATE_TABLE,
    DWS_FEATURE_SCHEMA,
    DWS_FEATURE_TABLE,
    TABLE_SCHEMAS,
)

FEATURE_VERSION = "risk-feature-v1"
RULE_VERSION = "risk-rule-v1"
SEVERITY = {
    RiskStatus.INSUFFICIENT_DATA.value: -1,
    RiskStatus.CLEAR.value: 0,
    RiskStatus.WATCH.value: 1,
    RiskStatus.ESCALATE.value: 2,
}


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    value = numerator / denominator
    return value if math.isfinite(value) else None


def _safe_growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    value = current / previous - 1.0
    return value if math.isfinite(value) else None


def _sum_required(*values: float | None) -> float | None:
    return sum(values) if values and all(value is not None for value in values) else None


def _apply_threshold(operator: str, value: float, threshold: float) -> bool:
    functions: dict[str, Callable[[float, float], bool]] = {
        "lt": lambda left, right: left < right,
        "le": lambda left, right: left <= right,
        "gt": lambda left, right: left > right,
        "ge": lambda left, right: left >= right,
        "eq": lambda left, right: left == right,
    }
    return functions[operator](value, threshold)


def _fingerprint(paths: list[Path], parameters: dict[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(parameters, sort_keys=True).encode("utf-8"))
    for path in sorted(paths):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _load_visible_facts(
    statement_root: Path,
    *,
    as_of_date: date,
    system_cutoff: datetime,
) -> tuple[pd.DataFrame, list[Path], int]:
    paths = sorted(statement_root.glob("companies/*/risk_facts.parquet"))
    if not paths:
        raise ValueError(f"no risk fact files found under {statement_root}")
    frame = pd.concat([pq.read_table(path).to_pandas() for path in paths], ignore_index=True)
    frame["report_period"] = pd.to_datetime(frame["report_period"]).dt.date
    frame["source_published_at"] = pd.to_datetime(frame["source_published_at"], utc=True)
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True)
    before = len(frame)
    visible = frame[
        (frame["source_published_at"].dt.date <= as_of_date)
        & (frame["observed_at"] <= system_cutoff)
        & frame["quality_passed"].astype(bool)
    ].copy()
    visible.sort_values(
        ["issuer_id", "report_period", "metric_code", "source_published_at", "observed_at"],
        inplace=True,
    )
    visible.drop_duplicates(
        ["issuer_id", "report_period", "metric_code"], keep="last", inplace=True
    )
    leak_count = before - len(
        frame[
            (frame["source_published_at"].dt.date <= as_of_date)
            & (frame["observed_at"] <= system_cutoff)
        ]
    )
    return visible, paths, leak_count


def _load_events(
    disclosure_root: Path | None, *, as_of_date: date, system_cutoff: datetime
) -> tuple[pd.DataFrame, list[Path]]:
    if disclosure_root is None:
        return pd.DataFrame(), []
    paths = sorted(disclosure_root.glob("companies/*/disclosure_events.parquet"))
    if not paths:
        return pd.DataFrame(), []
    frame = pd.concat([pq.read_table(path).to_pandas() for path in paths], ignore_index=True)
    frame["published_at"] = pd.to_datetime(frame["published_at"], utc=True)
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], utc=True)
    frame = frame[
        (frame["published_at"].dt.date <= as_of_date) & (frame["observed_at"] <= system_cutoff)
    ].copy()
    return frame, paths


def _value_maps(
    facts: pd.DataFrame,
) -> tuple[
    dict[tuple[str, date], dict[str, float | None]],
    dict[tuple[str, date], dict[str, str]],
]:
    values: dict[tuple[str, date], dict[str, float | None]] = defaultdict(dict)
    sources: dict[tuple[str, date], dict[str, str]] = defaultdict(dict)
    for row in facts.itertuples(index=False):
        key = (str(row.issuer_id), row.report_period)
        value = None
        if row.availability == DataAvailability.PRESENT.value and pd.notna(row.value):
            value = float(row.value)
        values[key][str(row.metric_code)] = value
        sources[key][str(row.metric_code)] = str(row.source_record_id)
    return values, sources


def _source_ids(
    source_map: dict[str, str], metrics: list[str], *, require_all: bool = True
) -> list[str]:
    present = [source_map[metric] for metric in metrics if metric in source_map]
    return present if not require_all or len(present) == len(metrics) else []


def compute_features(
    facts: pd.DataFrame,
    issuer_entries: list[dict[str, Any]],
    *,
    events: pd.DataFrame | None,
    as_of_date: date,
    data_snapshot_id: str,
    computed_at: datetime,
) -> list[dict[str, Any]]:
    values, sources = _value_maps(facts)
    registry = {item.code: item for item in RiskMetricRegistry.load_default().all()}
    entry_map = {str(item["issuer_id"]): item for item in issuer_entries}
    events = events if events is not None else pd.DataFrame()
    annual_periods: dict[str, list[date]] = defaultdict(list)
    for issuer_id, report_period in values:
        if report_period.month == 12 and report_period.day == 31:
            annual_periods[issuer_id].append(report_period)
    rows: list[dict[str, Any]] = []

    def add(
        issuer_id: str,
        report_period: date,
        code: str,
        value: float | None,
        source_ids: list[str],
        periods_used: int,
        *,
        availability: str | None = None,
    ) -> None:
        definition = registry[code]
        resolved_availability = availability or (
            DataAvailability.PRESENT.value
            if value is not None
            else DataAvailability.NOT_DISCLOSED.value
        )
        rows.append(
            {
                "issuer_id": issuer_id,
                "report_period": report_period,
                "as_of_date": as_of_date,
                "data_snapshot_id": data_snapshot_id,
                "metric_code": code,
                "metric_version": definition.version,
                "value": value,
                "unit": definition.unit,
                "availability": resolved_availability,
                "periods_used": periods_used,
                "source_fact_ids_json": json.dumps(source_ids, ensure_ascii=False),
                "computed_at": computed_at,
            }
        )

    for issuer_id, unsorted_periods in sorted(annual_periods.items()):
        periods = sorted(set(unsorted_periods))
        applicable = bool(entry_map.get(issuer_id, {}).get("generic_ratio_applicable", True))
        issuer_events = (
            events[events["issuer_id"].astype(str) == issuer_id]
            if not events.empty
            else pd.DataFrame()
        )
        for index, report_period in enumerate(periods):
            current = values[(issuer_id, report_period)]
            current_sources = sources[(issuer_id, report_period)]
            previous_period = periods[index - 1] if index >= 1 else None
            previous = values[(issuer_id, previous_period)] if previous_period else {}
            previous_sources = sources[(issuer_id, previous_period)] if previous_period else {}
            previous_two = periods[max(0, index - 2) : index + 1]
            if not applicable:
                for code, definition in registry.items():
                    if definition.category != RiskCategory.DISCLOSURE_AUDIT:
                        add(
                            issuer_id,
                            report_period,
                            code,
                            None,
                            [],
                            0,
                            availability=DataAvailability.NOT_AVAILABLE_FROM_SOURCE.value,
                        )
            else:
                add(
                    issuer_id,
                    report_period,
                    "current_ratio",
                    _safe_ratio(current.get("current_assets"), current.get("current_liabilities")),
                    _source_ids(current_sources, ["current_assets", "current_liabilities"]),
                    1,
                )
                short_debt = _sum_required(
                    current.get("short_term_borrowings"),
                    current.get("noncurrent_liabilities_due_within_one_year"),
                )
                add(
                    issuer_id,
                    report_period,
                    "cash_to_short_debt",
                    _safe_ratio(current.get("cash_and_equivalents"), short_debt),
                    _source_ids(
                        current_sources,
                        [
                            "cash_and_equivalents",
                            "short_term_borrowings",
                            "noncurrent_liabilities_due_within_one_year",
                        ],
                    ),
                    1,
                )
                add(
                    issuer_id,
                    report_period,
                    "ocf_to_current_liabilities",
                    _safe_ratio(
                        current.get("operating_cash_flow"), current.get("current_liabilities")
                    ),
                    _source_ids(
                        current_sources, ["operating_cash_flow", "current_liabilities"]
                    ),
                    1,
                )
                profit = current.get("parent_net_profit")
                ocf_profit_ratio = (
                    _safe_ratio(current.get("operating_cash_flow"), profit)
                    if profit is not None and profit > 0
                    else None
                )
                add(
                    issuer_id,
                    report_period,
                    "ocf_to_net_profit",
                    ocf_profit_ratio,
                    _source_ids(
                        current_sources, ["operating_cash_flow", "parent_net_profit"]
                    ),
                    1,
                )
                average_assets = (
                    _safe_ratio(
                        _sum_required(current.get("total_assets"), previous.get("total_assets")),
                        2.0,
                    )
                    if previous_period
                    else None
                )
                accruals = (
                    current.get("parent_net_profit") - current.get("operating_cash_flow")
                    if current.get("parent_net_profit") is not None
                    and current.get("operating_cash_flow") is not None
                    else None
                )
                add(
                    issuer_id,
                    report_period,
                    "accruals_to_assets",
                    _safe_ratio(accruals, average_assets),
                    _source_ids(
                        {**previous_sources, **current_sources},
                        ["parent_net_profit", "operating_cash_flow", "total_assets"],
                        require_all=False,
                    ),
                    2 if previous_period else 1,
                )
                divergence_values = [
                    values[(issuer_id, period)] for period in previous_two
                ]
                divergence = (
                    float(
                        sum(
                            item.get("parent_net_profit", 0) > 0
                            and item.get("operating_cash_flow", 0) < 0
                            for item in divergence_values
                        )
                    )
                    if len(divergence_values) == 3
                    and all(
                        item.get("parent_net_profit") is not None
                        and item.get("operating_cash_flow") is not None
                        for item in divergence_values
                    )
                    else None
                )
                divergence_sources = []
                for period in previous_two:
                    divergence_sources.extend(
                        _source_ids(
                            sources[(issuer_id, period)],
                            ["parent_net_profit", "operating_cash_flow"],
                        )
                    )
                add(
                    issuer_id,
                    report_period,
                    "profit_cashflow_divergence",
                    divergence,
                    divergence_sources,
                    len(previous_two),
                )
                receivables_code = (
                    "notes_and_accounts_receivable"
                    if current.get("notes_and_accounts_receivable") is not None
                    else "accounts_receivable"
                )
                previous_receivables_code = (
                    "notes_and_accounts_receivable"
                    if previous.get("notes_and_accounts_receivable") is not None
                    else "accounts_receivable"
                )
                receivables_growth = _safe_growth(
                    current.get(receivables_code), previous.get(previous_receivables_code)
                )
                revenue_growth = _safe_growth(
                    current.get("revenue"), previous.get("revenue")
                )
                add(
                    issuer_id,
                    report_period,
                    "receivables_revenue_growth_gap",
                    (
                        receivables_growth - revenue_growth
                        if receivables_growth is not None and revenue_growth is not None
                        else None
                    ),
                    _source_ids(
                        current_sources, [receivables_code, "revenue"], require_all=False
                    )
                    + _source_ids(
                        previous_sources,
                        [previous_receivables_code, "revenue"],
                        require_all=False,
                    ),
                    2 if previous_period else 1,
                )
                inventory_growth = _safe_growth(
                    current.get("inventory"), previous.get("inventory")
                )
                add(
                    issuer_id,
                    report_period,
                    "inventory_revenue_growth_gap",
                    (
                        inventory_growth - revenue_growth
                        if inventory_growth is not None and revenue_growth is not None
                        else None
                    ),
                    _source_ids(
                        current_sources, ["inventory", "revenue"], require_all=False
                    )
                    + _source_ids(
                        previous_sources, ["inventory", "revenue"], require_all=False
                    ),
                    2 if previous_period else 1,
                )
                add(
                    issuer_id,
                    report_period,
                    "goodwill_to_assets",
                    _safe_ratio(current.get("goodwill"), current.get("total_assets")),
                    _source_ids(current_sources, ["goodwill", "total_assets"]),
                    1,
                )
                impairment = _sum_required(
                    current.get("asset_impairment_loss"),
                    current.get("credit_impairment_loss"),
                )
                add(
                    issuer_id,
                    report_period,
                    "impairment_to_assets",
                    _safe_ratio(impairment, average_assets),
                    _source_ids(
                        {**previous_sources, **current_sources},
                        ["asset_impairment_loss", "credit_impairment_loss", "total_assets"],
                        require_all=False,
                    ),
                    2 if previous_period else 1,
                )

            add(
                issuer_id,
                report_period,
                "nonstandard_audit_opinion",
                current.get("audit_opinion_flag"),
                _source_ids(current_sources, ["audit_opinion_flag"]),
                1,
            )
            review_end = min(as_of_date, report_period + timedelta(days=550))
            window_events = (
                issuer_events[
                    (issuer_events["published_at"].dt.date > report_period)
                    & (issuer_events["published_at"].dt.date <= review_end)
                ]
                if not issuer_events.empty
                else pd.DataFrame()
            )
            for code, event_type in (
                ("financial_restatement", "financial_restatement"),
                ("financial_regulatory_inquiry", "regulatory_inquiry"),
            ):
                if issuer_events.empty:
                    add(
                        issuer_id,
                        report_period,
                        code,
                        None,
                        [],
                        0,
                        availability=DataAvailability.NOT_AVAILABLE_FROM_SOURCE.value,
                    )
                    continue
                matches = window_events[
                    window_events["event_types_json"].str.contains(
                        f'"{event_type}"', regex=False, na=False
                    )
                ]
                add(
                    issuer_id,
                    report_period,
                    code,
                    1.0 if not matches.empty else 0.0,
                    matches["event_id"].astype(str).tolist(),
                    1,
                )
    return rows


def score_candidates(
    features: list[dict[str, Any]], *, created_at: datetime
) -> list[dict[str, Any]]:
    registry = {item.code: item for item in RiskMetricRegistry.load_default().all()}
    by_period: dict[tuple[str, date, date, str], list[dict[str, Any]]] = defaultdict(list)
    for row in features:
        definition = registry[row["metric_code"]]
        key = (
            row["issuer_id"],
            row["report_period"],
            row["as_of_date"],
            definition.category.value,
        )
        by_period[key].append(row)
    candidates: list[dict[str, Any]] = []
    for key, rows in sorted(by_period.items()):
        issuer_id, report_period, as_of_date, category = key
        statuses: list[str] = []
        triggered: list[str] = []
        evidence_ids: set[str] = set()
        for row in rows:
            if row["availability"] != DataAvailability.PRESENT.value or row["value"] is None:
                continue
            status = RiskStatus.CLEAR.value
            for threshold in registry[row["metric_code"]].thresholds:
                if _apply_threshold(threshold.operator, row["value"], threshold.value):
                    if SEVERITY[threshold.status] > SEVERITY[status]:
                        status = threshold.status
            statuses.append(status)
            if status in {RiskStatus.WATCH.value, RiskStatus.ESCALATE.value}:
                triggered.append(row["metric_code"])
                evidence_ids.update(json.loads(row["source_fact_ids_json"]))
        status = (
            max(statuses, key=lambda value: SEVERITY[value])
            if statuses
            else RiskStatus.INSUFFICIENT_DATA.value
        )
        payload = f"{issuer_id}|{report_period}|{as_of_date}|{category}|{RULE_VERSION}"
        candidate_id = "candidate-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
        candidates.append(
            {
                "candidate_id": candidate_id,
                "issuer_id": issuer_id,
                "report_period": report_period,
                "as_of_date": as_of_date,
                "data_snapshot_id": rows[0]["data_snapshot_id"],
                "risk_category": category,
                "status": status,
                "rule_score": {
                    RiskStatus.ESCALATE.value: 1.0,
                    RiskStatus.WATCH.value: 0.5,
                    RiskStatus.CLEAR.value: 0.0,
                }.get(status),
                "triggered_metrics_json": json.dumps(sorted(triggered), ensure_ascii=False),
                "evidence_ids_json": json.dumps(sorted(evidence_ids), ensure_ascii=False),
                "created_at": created_at,
            }
        )
    return candidates


def _write_iceberg(
    root: Path,
    *,
    fingerprint: str,
    feature_table: pa.Table,
    candidate_table: pa.Table,
) -> dict[str, Any]:
    iceberg_root = root / "iceberg" / fingerprint[:16]
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
    snapshots: dict[str, Any] = {}
    for table_name, table_data, version in (
        (DWS_FEATURE_TABLE, feature_table, FEATURE_VERSION),
        (ADS_CANDIDATE_TABLE, candidate_table, RULE_VERSION),
    ):
        table = repository.catalog.load_table(table_name)
        snapshot = table.current_snapshot()
        reused = snapshot is not None
        if snapshot is None:
            ingestion = IngestionBatch(
                batch_id=f"{version}-{fingerprint[:12]}",
                dataset=table_name.split(".")[-1],
                tier=DataTier.DERIVED,
                source=SourceMetadata(
                    source="issuer_risk_features_v1",
                    endpoint="offline_feature_pipeline",
                    mapping_version=version,
                    parameters={"input_fingerprint": fingerprint},
                ),
                input_rows=table_data.num_rows,
                output_rows=table_data.num_rows,
            )
            completed = repository.append(
                table_name, table_data, ingestion, BatchMetadataStore(settings.lake_root)
            )
            snapshot_id = completed.snapshot_id
            table = repository.catalog.load_table(table_name)
        else:
            snapshot_id = snapshot.snapshot_id
        snapshots[table_name] = {
            "rows": table.scan().to_arrow().num_rows,
            "snapshot_id": snapshot_id,
            "reused": reused,
        }
    return {
        "catalog": str(iceberg_root / "catalog.db"),
        "warehouse": str(iceberg_root / "warehouse"),
        "tables": snapshots,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Point-in-Time 特征与规则候选报告",
        "",
        f"- 数据快照：`{report['data_snapshot_id']}`",
        f"- 分析截止日：`{report['as_of_date']}`",
        f"- 公司覆盖：{report['company_count']}",
        f"- 特征行数：{report['feature_count']}",
        f"- 规则候选行数：{report['candidate_count']}",
        f"- PIT 越界进入输出：{report['pit_output_leak_count']}",
        "",
        "## 特征可用性",
        "",
        "```json",
        json.dumps(report["feature_availability"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## 候选状态",
        "",
        "```json",
        json.dumps(report["candidate_status"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## 限制",
        "",
        "公告标题规则仅产生待复核信号；当前 Eastmoney 快照采用 NOTICE_DATE 与 UPDATE_DATE 的较晚值，"
        "因此不会把当前修订后的值伪装成历史时点值。",
    ]
    return "\n".join(lines)


def run_pipeline(
    root: Path,
    *,
    statement_root: Path,
    pool_file: Path,
    disclosure_root: Path | None,
    as_of_date: date,
    system_cutoff: datetime,
) -> tuple[Path, Path]:
    if system_cutoff.tzinfo is None:
        raise ValueError("system_cutoff must be timezone-aware")
    root.mkdir(parents=True, exist_ok=True)
    pool = json.loads(pool_file.read_text(encoding="utf-8"))
    facts, fact_paths, excluded_by_boundary = _load_visible_facts(
        statement_root, as_of_date=as_of_date, system_cutoff=system_cutoff
    )
    events, event_paths = _load_events(
        disclosure_root, as_of_date=as_of_date, system_cutoff=system_cutoff
    )
    fingerprint = _fingerprint(
        fact_paths + event_paths + [pool_file],
        {
            "feature_version": FEATURE_VERSION,
            "rule_version": RULE_VERSION,
            "metric_registry_sha256": hashlib.sha256(
                files("financial_research_agent.risk")
                .joinpath("risk_metrics_v1.json")
                .read_bytes()
            ).hexdigest(),
            "as_of_date": as_of_date.isoformat(),
            "system_cutoff": system_cutoff.isoformat(),
        },
    )
    snapshot_id = f"sha256:{fingerprint}"
    computed_at = system_cutoff.astimezone(timezone.utc)
    features = compute_features(
        facts,
        pool["entries"],
        events=events,
        as_of_date=as_of_date,
        data_snapshot_id=snapshot_id,
        computed_at=computed_at,
    )
    candidates = score_candidates(features, created_at=computed_at)
    feature_arrow = pa.Table.from_pylist(features).select(
        [field.name for field in DWS_FEATURE_SCHEMA.fields]
    )
    feature_arrow = feature_arrow.cast(schema_to_pyarrow(DWS_FEATURE_SCHEMA), safe=False)
    candidate_arrow = pa.Table.from_pylist(candidates).select(
        [field.name for field in ADS_CANDIDATE_SCHEMA.fields]
    )
    candidate_arrow = candidate_arrow.cast(schema_to_pyarrow(ADS_CANDIDATE_SCHEMA), safe=False)
    feature_path = root / "risk_features.parquet"
    candidate_path = root / "risk_candidates.parquet"
    pq.write_table(feature_arrow, feature_path, compression="zstd")
    pq.write_table(candidate_arrow, candidate_path, compression="zstd")
    feature_keys = [
        (row["issuer_id"], row["report_period"], row["as_of_date"], row["metric_code"])
        for row in features
    ]
    candidate_keys = [row["candidate_id"] for row in candidates]
    output_leaks = int(
        (
            (facts["source_published_at"].dt.date > as_of_date)
            | (facts["observed_at"] > pd.Timestamp(system_cutoff))
        ).sum()
    )
    iceberg = _write_iceberg(
        root,
        fingerprint=fingerprint,
        feature_table=feature_arrow,
        candidate_table=candidate_arrow,
    )
    report = {
        "feature_version": FEATURE_VERSION,
        "rule_version": RULE_VERSION,
        "data_snapshot_id": snapshot_id,
        "input_fingerprint": fingerprint,
        "as_of_date": as_of_date.isoformat(),
        "system_cutoff": system_cutoff.isoformat(),
        "company_count": len({row["issuer_id"] for row in features}),
        "feature_count": len(features),
        "candidate_count": len(candidates),
        "feature_availability": dict(
            sorted(Counter(row["availability"] for row in features).items())
        ),
        "candidate_status": dict(sorted(Counter(row["status"] for row in candidates).items())),
        "feature_primary_key_duplicates": len(feature_keys) - len(set(feature_keys)),
        "candidate_primary_key_duplicates": len(candidate_keys) - len(set(candidate_keys)),
        "records_excluded_by_pit_boundary": excluded_by_boundary,
        "pit_output_leak_count": output_leaks,
        "iceberg": iceberg,
        "generated_at": computed_at.isoformat(),
    }
    json_path = root / "report.json"
    markdown_path = root / "report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Point-in-Time financial-risk features")
    parser.add_argument("--root", default="/artifacts/risk_data/features_v1")
    parser.add_argument(
        "--statement-root", default="/artifacts/risk_data/expansion_statements_v1"
    )
    parser.add_argument(
        "--pool-file",
        default="/artifacts/risk_data/expansion_pool_v1/expansion_pool_v1.json",
    )
    parser.add_argument(
        "--disclosure-root", default="/artifacts/risk_data/disclosure_pool_v1"
    )
    parser.add_argument("--as-of-date", default="2026-09-07")
    parser.add_argument("--system-cutoff", default="2026-09-07T23:59:59+00:00")
    args = parser.parse_args()
    paths = run_pipeline(
        Path(args.root),
        statement_root=Path(args.statement_root),
        pool_file=Path(args.pool_file),
        disclosure_root=Path(args.disclosure_root) if args.disclosure_root else None,
        as_of_date=date.fromisoformat(args.as_of_date),
        system_cutoff=datetime.fromisoformat(args.system_cutoff),
    )
    print(json.dumps({"json": str(paths[0]), "markdown": str(paths[1])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
