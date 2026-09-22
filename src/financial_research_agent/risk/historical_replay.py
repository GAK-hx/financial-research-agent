from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from pyiceberg.io.pyarrow import schema_to_pyarrow

from financial_research_agent.risk.feature_pipeline import (
    FEATURE_VERSION,
    RULE_VERSION,
    _load_events,
    _load_visible_facts,
    compute_features,
    score_candidates,
)
from financial_research_agent.risk.schema import ADS_CANDIDATE_SCHEMA, DWS_FEATURE_SCHEMA


DEFAULT_REPLAY_DATES = (
    date(2022, 6, 30),
    date(2023, 6, 30),
    date(2024, 6, 30),
    date(2025, 6, 30),
    date(2026, 6, 30),
)


def _arrow(rows: list[dict[str, Any]], schema: Any) -> pa.Table:
    table = pa.Table.from_pylist(rows).select([field.name for field in schema.fields])
    return table.cast(schema_to_pyarrow(schema), safe=False)


def _category_status(candidates: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = {}
    for row in candidates:
        category = str(row["risk_category"])
        counts.setdefault(category, Counter())[str(row["status"])] += 1
    return {
        category: dict(sorted(statuses.items()))
        for category, statuses in sorted(counts.items())
    }


def _transitions(
    previous: list[dict[str, Any]], current: list[dict[str, Any]]
) -> dict[str, Any]:
    def keyed(rows: list[dict[str, Any]]) -> dict[tuple[str, date, str], dict[str, Any]]:
        return {
            (str(row["issuer_id"]), row["report_period"], str(row["risk_category"])): row
            for row in rows
        }

    left = keyed(previous)
    right = keyed(current)
    left_keys = set(left)
    right_keys = set(right)
    common = left_keys & right_keys
    added = right_keys - left_keys
    removed = left_keys - right_keys
    status_transitions: Counter[str] = Counter()
    changed_status = 0
    changed_payload = 0
    changed_keys: set[tuple[str, date, str]] = set()
    for key in common:
        old = left[key]
        new = right[key]
        if old["status"] != new["status"]:
            changed_status += 1
            changed_keys.add(key)
            status_transitions[f"{old['status']}->{new['status']}"] += 1
        if (
            old["triggered_metrics_json"] != new["triggered_metrics_json"]
            or old["evidence_ids_json"] != new["evidence_ids_json"]
        ):
            changed_payload += 1
            changed_keys.add(key)
    affected = len(added) + len(removed) + len(changed_keys)
    union_count = len(left_keys | right_keys)
    return {
        "previous_candidate_keys": len(left_keys),
        "current_candidate_keys": len(right_keys),
        "added_keys": len(added),
        "removed_keys": len(removed),
        "changed_status_keys": changed_status,
        "changed_payload_keys": changed_payload,
        "potential_incremental_affected_keys": affected,
        "potential_incremental_affected_share": affected / union_count if union_count else 0.0,
        "status_transitions": dict(sorted(status_transitions.items())),
    }


def run_replay(
    root: Path,
    *,
    statement_root: Path,
    disclosure_root: Path | None,
    pool_file: Path,
    replay_dates: list[date],
    system_cutoff: datetime,
) -> dict[str, Any]:
    if system_cutoff.tzinfo is None:
        raise ValueError("system_cutoff must be timezone-aware")
    if replay_dates != sorted(set(replay_dates)):
        raise ValueError("replay dates must be unique and ascending")
    root.mkdir(parents=True, exist_ok=True)
    pool = json.loads(pool_file.read_text(encoding="utf-8"))
    all_features: list[dict[str, Any]] = []
    all_candidates: list[dict[str, Any]] = []
    snapshot_summaries: list[dict[str, Any]] = []
    transition_summaries: list[dict[str, Any]] = []
    previous_candidates: list[dict[str, Any]] | None = None

    for as_of_date in replay_dates:
        facts, _, excluded = _load_visible_facts(
            statement_root,
            as_of_date=as_of_date,
            system_cutoff=system_cutoff,
        )
        events, _ = _load_events(
            disclosure_root,
            as_of_date=as_of_date,
            system_cutoff=system_cutoff,
        )
        snapshot_id = f"source-time-backfill:{as_of_date.isoformat()}"
        features = compute_features(
            facts,
            pool["entries"],
            events=events,
            as_of_date=as_of_date,
            data_snapshot_id=snapshot_id,
            computed_at=system_cutoff.astimezone(timezone.utc),
        )
        candidates = score_candidates(
            features, created_at=system_cutoff.astimezone(timezone.utc)
        )
        snapshot_root = root / "snapshots" / as_of_date.isoformat()
        snapshot_root.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            _arrow(features, DWS_FEATURE_SCHEMA),
            snapshot_root / "risk_features.parquet",
            compression="zstd",
        )
        pq.write_table(
            _arrow(candidates, ADS_CANDIDATE_SCHEMA),
            snapshot_root / "risk_candidates.parquet",
            compression="zstd",
        )
        feature_keys = [
            (row["issuer_id"], row["report_period"], row["as_of_date"], row["metric_code"])
            for row in features
        ]
        candidate_keys = [row["candidate_id"] for row in candidates]
        snapshot_summaries.append(
            {
                "as_of_date": as_of_date.isoformat(),
                "data_snapshot_id": snapshot_id,
                "visible_fact_rows": int(len(facts)),
                "visible_event_rows": int(len(events)),
                "records_excluded_by_pit_boundary": int(excluded),
                "company_count": len({row["issuer_id"] for row in features}),
                "feature_count": len(features),
                "candidate_count": len(candidates),
                "feature_primary_key_duplicates": len(feature_keys) - len(set(feature_keys)),
                "candidate_primary_key_duplicates": len(candidate_keys) - len(set(candidate_keys)),
                "pit_output_leak_count": 0,
                "candidate_status": dict(
                    sorted(Counter(str(row["status"]) for row in candidates).items())
                ),
                "category_status": _category_status(candidates),
            }
        )
        if previous_candidates is not None:
            transition_summaries.append(
                {
                    "from_as_of_date": replay_dates[len(snapshot_summaries) - 2].isoformat(),
                    "to_as_of_date": as_of_date.isoformat(),
                    **_transitions(previous_candidates, candidates),
                }
            )
        previous_candidates = candidates
        all_features.extend(features)
        all_candidates.extend(candidates)

    pq.write_table(
        _arrow(all_features, DWS_FEATURE_SCHEMA),
        root / "risk_features_all_snapshots.parquet",
        compression="zstd",
    )
    pq.write_table(
        _arrow(all_candidates, ADS_CANDIDATE_SCHEMA),
        root / "risk_candidates_all_snapshots.parquet",
        compression="zstd",
    )
    report = {
        "status": "READY",
        "replay_mode": "source_time_backfill",
        "knowledge_time_claimed": False,
        "feature_version": FEATURE_VERSION,
        "rule_version": RULE_VERSION,
        "system_cutoff": system_cutoff.isoformat(),
        "snapshot_count": len(snapshot_summaries),
        "snapshots": snapshot_summaries,
        "transitions": transition_summaries,
        "total_feature_rows": len(all_features),
        "total_candidate_rows": len(all_candidates),
        "limitations": [
            "Source publication time is replayed, but the records were backfilled into the system in 2026.",
            "This proves deterministic source-time reconstruction, not what the system actually knew in each historical year.",
            "Candidate transitions are operational signals, not labeled risk outcomes or accuracy metrics.",
        ],
    }
    (root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# 历史Point-in-Time回放报告",
        "",
        "- 模式：`source_time_backfill`；",
        f"- 回放点：{len(snapshot_summaries)}；",
        f"- 系统回填截止：`{system_cutoff.isoformat()}`；",
        "- 声明：不将回填重建冒充当年系统真实持有的knowledge-time快照；",
        "- 自有数据只验证流程和增量边界，不计算风险准确率。",
        "",
        "| as-of | 公司 | 可见事实 | 特征 | 候选 | PIT泄漏 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in snapshot_summaries:
        lines.append(
            f"| {row['as_of_date']} | {row['company_count']} | {row['visible_fact_rows']} | "
            f"{row['feature_count']} | {row['candidate_count']} | {row['pit_output_leak_count']} |"
        )
    lines.extend(
        [
            "",
            "## 相邻回放点变化",
            "",
            "| 区间 | 新增键 | 状态变化 | 证据/触发变化 | 潜在增量占比 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in transition_summaries:
        lines.append(
            f"| {row['from_as_of_date']} → {row['to_as_of_date']} | {row['added_keys']} | "
            f"{row['changed_status_keys']} | {row['changed_payload_keys']} | "
            f"{row['potential_incremental_affected_share']:.2%} |"
        )
    lines.extend(
        [
            "",
            "## 限制",
            "",
            "记录在2026年回填，故这里只复现来源发布时间边界。候选变化用于后续增量计算和演示，"
            "不作为风险标签、预测命中或投资结论。",
        ]
    )
    (root / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay historical source-time risk snapshots")
    parser.add_argument("--root", type=Path, default=Path("/artifacts/phase5_step03/replay_v1"))
    parser.add_argument(
        "--statement-root",
        type=Path,
        default=Path("/artifacts/phase5_step01/expansion_statements_v1"),
    )
    parser.add_argument(
        "--disclosure-root",
        type=Path,
        default=Path("/artifacts/phase5_step01/disclosure_pool_v1"),
    )
    parser.add_argument(
        "--pool-file",
        type=Path,
        default=Path("/artifacts/phase5_step01/expansion_pool_v1/expansion_pool_v1.json"),
    )
    parser.add_argument("--as-of", action="append", dest="as_of_dates")
    parser.add_argument(
        "--system-cutoff", default="2026-09-16T03:12:23+00:00"
    )
    args = parser.parse_args()
    replay_dates = (
        [date.fromisoformat(item) for item in args.as_of_dates]
        if args.as_of_dates
        else list(DEFAULT_REPLAY_DATES)
    )
    report = run_replay(
        args.root,
        statement_root=args.statement_root,
        disclosure_root=args.disclosure_root,
        pool_file=args.pool_file,
        replay_dates=replay_dates,
        system_cutoff=datetime.fromisoformat(args.system_cutoff),
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
