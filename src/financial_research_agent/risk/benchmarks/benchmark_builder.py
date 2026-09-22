from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from financial_research_agent.risk.domain.models import (
    BenchmarkExpectedAnswer,
    BenchmarkSplit,
    EvidencePointer,
    IssuerRiskCase,
    PointInTimeBoundary,
)

DATASET_VERSION = "issuer-risk-bench-v1"
RANDOM_SEED = 20260907
TASK_QUOTAS = {
    "retrieval": 50,
    "calculation": 50,
    "risk_detection": 60,
    "evidence_validation": 50,
    "counterevidence": 40,
    "team_selection": 30,
    "missing_or_conflict": 20,
}
STATUS_SEVERITY = {"insufficient_data": -1, "clear": 0, "watch": 1, "escalate": 2}
CATEGORY_AGENTS = {
    "liquidity": "liquidity_agent",
    "earnings_quality": "earnings_quality_agent",
    "asset_quality": "asset_quality_agent",
    "disclosure_audit": "disclosure_agent",
}


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _evidence_from_fact(row: pd.Series) -> EvidencePointer:
    digest = hashlib.sha256(str(row["source_record_id"]).encode("utf-8")).hexdigest()[:20]
    published_at = pd.Timestamp(row["source_published_at"]).to_pydatetime()
    return EvidencePointer(
        evidence_id=f"evidence:fact:{digest}",
        source_name=str(row["source_name"]),
        source_record_id=str(row["source_record_id"]),
        content_sha256=str(row["content_sha256"]),
        published_at=published_at,
        locator=(
            "iceberg://financial.risk_fact_pit?issuer_id="
            f"{row['issuer_id']}&report_period={row['report_period']}&metric={row['metric_code']}"
        ),
    )


def _task_schedule() -> list[str]:
    tasks = [task for task, count in TASK_QUOTAS.items() for _ in range(count)]
    random.Random(RANDOM_SEED).shuffle(tasks)
    return tasks


def _present_facts(facts: pd.DataFrame, issuer_id: str, report_period: date) -> pd.DataFrame:
    return facts[
        (facts["issuer_id"].astype(str) == issuer_id)
        & (facts["report_period"] == report_period)
        & (facts["availability"] == "present")
        & facts["value"].notna()
    ].copy()


def _choose_candidate(candidates: pd.DataFrame, issuer_id: str, report_period: date) -> pd.Series:
    options = candidates[
        (candidates["issuer_id"].astype(str) == issuer_id)
        & (candidates["report_period"] == report_period)
    ].copy()
    if options.empty:
        raise ValueError(f"no candidate for {issuer_id} {report_period}")
    options["severity"] = options["status"].map(STATUS_SEVERITY)
    return options.sort_values(["severity", "risk_category"], ascending=[False, True]).iloc[0]


def _build_case(
    *,
    case_number: int,
    issuer_id: str,
    issuer_name: str,
    report_period: date,
    split: BenchmarkSplit,
    task_type: str,
    snapshot_id: str,
    as_of_date: date,
    system_cutoff: datetime,
    facts: pd.DataFrame,
    features: pd.DataFrame,
    candidates: pd.DataFrame,
) -> IssuerRiskCase:
    period_facts = _present_facts(facts, issuer_id, report_period)
    period_features = features[
        (features["issuer_id"].astype(str) == issuer_id)
        & (features["report_period"] == report_period)
    ].copy()
    candidate = _choose_candidate(candidates, issuer_id, report_period)
    evidence: list[EvidencePointer] = []
    annotation_status = "deterministic_verified"

    if task_type in {"retrieval", "evidence_validation"}:
        preferred = [
            "revenue",
            "operating_cash_flow",
            "parent_net_profit",
            "current_liabilities",
            "total_assets",
        ]
        available = period_facts.set_index("metric_code", drop=False)
        selected = next(
            (available.loc[metric] for metric in preferred if metric in available.index),
            period_facts.iloc[0],
        )
        if isinstance(selected, pd.DataFrame):
            selected = selected.iloc[0]
        pointer = _evidence_from_fact(selected)
        evidence = [pointer]
        if task_type == "retrieval":
            question = (
                f"截至{as_of_date}，检索{issuer_name}（{issuer_id}）{report_period}的"
                f"{selected['metric_code']}，返回数值、单位、发布日期和来源。"
            )
            expected = BenchmarkExpectedAnswer(
                answer_type="fact",
                payload={
                    "metric_code": str(selected["metric_code"]),
                    "value": float(selected["value"]),
                    "unit": str(selected["unit"]),
                    "source_published_at": pd.Timestamp(
                        selected["source_published_at"]
                    ).isoformat(),
                },
                evidence_ids=[pointer.evidence_id],
                numeric_tolerance=max(abs(float(selected["value"])) * 1e-9, 1e-6),
            )
        else:
            question = (
                f"核验{issuer_name}（{issuer_id}）{report_period}的"
                f"{selected['metric_code']}是否由给定来源记录直接支持。"
            )
            expected = BenchmarkExpectedAnswer(
                answer_type="evidence",
                payload={
                    "supported": True,
                    "metric_code": str(selected["metric_code"]),
                    "content_sha256": str(selected["content_sha256"]),
                },
                evidence_ids=[pointer.evidence_id],
            )
    elif task_type == "calculation":
        available = period_features[
            (period_features["availability"] == "present")
            & period_features["value"].notna()
        ].sort_values("metric_code")
        selected = available.iloc[case_number % len(available)]
        source_ids = json.loads(selected["source_fact_ids_json"])
        fact_by_source = facts.set_index("source_record_id", drop=False)
        for source_id in source_ids[:4]:
            if source_id in fact_by_source.index:
                source = fact_by_source.loc[source_id]
                if isinstance(source, pd.DataFrame):
                    source = source.iloc[0]
                evidence.append(_evidence_from_fact(source))
        question = (
            f"计算{issuer_name}（{issuer_id}）{report_period}的{selected['metric_code']}，"
            "返回口径、数值、量纲和输入证据。"
        )
        expected = BenchmarkExpectedAnswer(
            answer_type="calculation",
            payload={
                "metric_code": str(selected["metric_code"]),
                "value": float(selected["value"]),
                "unit": str(selected["unit"]),
                "metric_version": str(selected["metric_version"]),
            },
            evidence_ids=[item.evidence_id for item in evidence],
            numeric_tolerance=max(abs(float(selected["value"])) * 1e-6, 1e-8),
        )
    elif task_type == "missing_or_conflict":
        unavailable = period_features[period_features["availability"] != "present"]
        selected = unavailable.iloc[0] if not unavailable.empty else period_features.iloc[0]
        question = (
            f"评估{issuer_name}（{issuer_id}）{report_period}的{selected['metric_code']}；"
            "若输入不足，不得用0或模型猜测补值。"
        )
        expected = BenchmarkExpectedAnswer(
            answer_type="missing_data",
            payload={
                "metric_code": str(selected["metric_code"]),
                "availability": str(selected["availability"]),
                "required_action": "insufficient_data_or_explicit_limitation",
            },
        )
    elif task_type == "team_selection":
        category = str(candidate["risk_category"])
        team = ["financial_statement_agent", CATEGORY_AGENTS[category]]
        if candidate["status"] in {"watch", "escalate"}:
            team.append("counterevidence_agent")
        if category == "disclosure_audit":
            team.append("evidence_validation_agent")
        question = (
            f"为{issuer_name}（{issuer_id}）{report_period}的{category}风险复核选择最小必要子Agent集合。"
        )
        expected = BenchmarkExpectedAnswer(
            answer_type="agent_team",
            payload={"acceptable_agents": sorted(set(team)), "category": category},
        )
        annotation_status = "design_reference"
    else:
        category = str(candidate["risk_category"])
        status = str(candidate["status"])
        triggered = json.loads(candidate["triggered_metrics_json"])
        question = (
            f"截至{as_of_date}，判断{issuer_name}（{issuer_id}）{report_period}的"
            f"{category}风险候选状态，并说明支持证据、反证和限制。"
        )
        expected = BenchmarkExpectedAnswer(
            answer_type=(
                "counterevidence" if task_type == "counterevidence" else "risk_candidate"
            ),
            payload={
                "rule_baseline_status": status,
                "risk_category": category,
                "triggered_metrics": triggered,
                "human_label_required": True,
            },
        )
        annotation_status = "pending_human_review"

    return IssuerRiskCase(
        case_id=f"irb-{case_number:04d}",
        dataset_version=DATASET_VERSION,
        split=split,
        issuer_id=issuer_id,
        report_period=report_period,
        boundary=PointInTimeBoundary(
            as_of_date=as_of_date,
            system_cutoff=system_cutoff,
            data_snapshot_id=snapshot_id,
        ),
        task_type=task_type,
        question=question,
        expected_answer=expected,
        annotation_status=annotation_status,
        evidence=evidence,
    )


def _annotation_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    recent = candidates[
        pd.to_datetime(candidates["report_period"]).dt.year >= 2020
    ].copy()

    def balanced_sample(frame: pd.DataFrame, count: int) -> pd.DataFrame:
        ordered = frame.sort_values(
            ["issuer_id", "report_period", "risk_category"],
            ascending=[True, False, True],
            kind="stable",
        ).copy()
        ordered["issuer_sample_rank"] = ordered.groupby("issuer_id").cumcount()
        return ordered.sort_values(
            ["issuer_sample_rank", "issuer_id", "report_period", "risk_category"],
            ascending=[True, True, False, True],
            kind="stable",
        ).head(count).drop(columns=["issuer_sample_rank"])

    risk = balanced_sample(recent[recent["status"].isin(["escalate", "watch"])], 120)
    controls = balanced_sample(recent[recent["status"] == "clear"], 120)
    insufficient = balanced_sample(
        recent[recent["status"] == "insufficient_data"], 60
    )
    if (len(risk), len(controls), len(insufficient)) != (120, 120, 60):
        raise ValueError(
            "cannot freeze 120 risk candidates, 120 controls and 60 insufficient cases"
        )
    risk["candidate_group"] = "risk_candidate"
    controls["candidate_group"] = "control"
    insufficient["candidate_group"] = "insufficient_or_conflict"
    combined = pd.concat([risk, controls, insufficient], ignore_index=True)
    return combined.sample(frac=1.0, random_state=RANDOM_SEED).reset_index(drop=True)


def _write_annotation_packets(
    root: Path,
    candidates: pd.DataFrame,
    *,
    features: pd.DataFrame,
    issuer_names: dict[str, str],
) -> dict[str, Any]:
    annotation_root = root / "annotations"
    annotation_root.mkdir(parents=True, exist_ok=True)
    samples = []
    for group in ("risk_candidate", "control", "insufficient_or_conflict"):
        samples.append(candidates[candidates["candidate_group"] == group].head(10))
    selected = pd.concat(samples, ignore_index=True)
    key_path = annotation_root / "review_key_private.csv"
    selected.to_csv(key_path, index=False)
    key_path.chmod(0o600)
    packet = selected[
        [
            "candidate_id",
            "issuer_id",
            "report_period",
            "risk_category",
            "triggered_metrics_json",
            "evidence_ids_json",
        ]
    ].copy()
    packet.insert(
        2,
        "issuer_name",
        packet["issuer_id"].astype(str).map(issuer_names),
    )
    feature_context = {}
    for row in features.itertuples(index=False):
        key = (str(row.issuer_id), row.report_period)
        feature_context.setdefault(key, {})[str(row.metric_code)] = {
            "value": None if pd.isna(row.value) else float(row.value),
            "unit": str(row.unit),
            "availability": str(row.availability),
            "source_fact_ids": json.loads(row.source_fact_ids_json),
        }
    packet["feature_context_json"] = [
        json.dumps(feature_context.get((str(row.issuer_id), row.report_period), {}), ensure_ascii=False)
        for row in packet.itertuples(index=False)
    ]
    packet["human_status"] = ""
    packet["human_categories"] = ""
    packet["evidence_sufficient"] = ""
    packet["rationale"] = ""
    paths = {}
    for index, annotator in enumerate(("annotator_a", "annotator_b")):
        path = annotation_root / f"{annotator}.csv"
        if path.exists():
            prior = pd.read_csv(path, dtype=str).fillna("")
            if "human_status" in prior and prior["human_status"].astype(bool).any():
                raise ValueError(f"{path} already contains human labels; refusing overwrite")
        packet.sample(frac=1.0, random_state=RANDOM_SEED + index).to_csv(path, index=False)
        paths[annotator] = str(path)
    return {
        "review_case_count": len(packet),
        "packets": paths,
        "private_review_key": str(key_path),
        "private_review_key_mode": oct(key_path.stat().st_mode & 0o777),
    }


def _markdown(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# IssuerRiskBench v1 构建报告",
            "",
            f"- 总案例：{report['case_count']}",
            f"- 开发集：{report['development_count']}",
            f"- 私有 Holdout：{report['private_holdout_count']}",
            f"- 公司跨集合重叠：{report['issuer_overlap_count']}",
            f"- 任务分布：`{json.dumps(report['task_counts'], ensure_ascii=False)}`",
            f"- 标注候选：`{json.dumps(report['annotation_candidate_counts'], ensure_ascii=False)}`",
            "",
            "风险识别与反证案例当前只保存规则基线，状态为 `pending_human_review`，不得作为人工 Gold 标签计分。",
            "检索、计算与来源核验案例由快照确定性生成；私有 Holdout 内容不写入开发集目录。",
        ]
    )


def build_benchmark(
    root: Path,
    *,
    statement_root: Path,
    pool_file: Path,
    feature_root: Path,
) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    pool = json.loads(pool_file.read_text(encoding="utf-8"))
    feature_report = json.loads((feature_root / "report.json").read_text(encoding="utf-8"))
    facts = pd.concat(
        [
            pq.read_table(path).to_pandas()
            for path in sorted(statement_root.glob("companies/*/risk_facts.parquet"))
        ],
        ignore_index=True,
    )
    facts["report_period"] = pd.to_datetime(facts["report_period"]).dt.date
    features = pq.read_table(feature_root / "risk_features.parquet").to_pandas()
    candidates = pq.read_table(feature_root / "risk_candidates.parquet").to_pandas()
    features["report_period"] = pd.to_datetime(features["report_period"]).dt.date
    candidates["report_period"] = pd.to_datetime(candidates["report_period"]).dt.date
    issuer_names = {str(item["issuer_id"]): str(item["issuer_name"]) for item in pool["entries"]}
    issuers = sorted(set(features["issuer_id"].astype(str)) & set(issuer_names))
    if len(issuers) != 100:
        raise ValueError(f"benchmark requires exactly 100 covered issuers, found {len(issuers)}")
    task_schedule = _task_schedule()
    cases: list[IssuerRiskCase] = []
    for issuer_index, issuer_id in enumerate(issuers):
        issuer_periods = sorted(
            set(features[features["issuer_id"].astype(str) == issuer_id]["report_period"])
        )
        report_period = issuer_periods[-1]
        split = (
            BenchmarkSplit.DEVELOPMENT
            if issuer_index < 60
            else BenchmarkSplit.PRIVATE_HOLDOUT
        )
        for offset in range(3):
            case_number = issuer_index * 3 + offset + 1
            cases.append(
                _build_case(
                    case_number=case_number,
                    issuer_id=issuer_id,
                    issuer_name=issuer_names[issuer_id],
                    report_period=report_period,
                    split=split,
                    task_type=task_schedule[case_number - 1],
                    snapshot_id=feature_report["data_snapshot_id"],
                    as_of_date=date.fromisoformat(feature_report["as_of_date"]),
                    system_cutoff=datetime.fromisoformat(feature_report["system_cutoff"]),
                    facts=facts,
                    features=features,
                    candidates=candidates,
                )
            )
    serialised = [case.model_dump(mode="json") for case in cases]
    development = [row for row in serialised if row["split"] == "development"]
    holdout = [row for row in serialised if row["split"] == "private_holdout"]
    development_path = root / "development" / "cases.jsonl"
    holdout_path = root / "private_holdout" / "cases.jsonl"
    _write_jsonl(development_path, development)
    _write_jsonl(holdout_path, holdout)
    holdout_path.chmod(0o600)
    annotation_candidates = _annotation_candidates(candidates)
    annotation_path = root / "annotation_candidates.parquet"
    annotation_candidates.to_parquet(annotation_path, index=False)
    annotation_packets = _write_annotation_packets(
        root,
        annotation_candidates,
        features=features,
        issuer_names=issuer_names,
    )
    development_issuers = {row["issuer_id"] for row in development}
    holdout_issuers = {row["issuer_id"] for row in holdout}
    report = {
        "dataset_version": DATASET_VERSION,
        "random_seed": RANDOM_SEED,
        "case_count": len(serialised),
        "development_count": len(development),
        "private_holdout_count": len(holdout),
        "development_issuer_count": len(development_issuers),
        "private_holdout_issuer_count": len(holdout_issuers),
        "issuer_overlap_count": len(development_issuers & holdout_issuers),
        "task_counts": dict(sorted(Counter(row["task_type"] for row in serialised).items())),
        "annotation_status_counts": dict(
            sorted(Counter(row["annotation_status"] for row in serialised).items())
        ),
        "annotation_candidate_counts": dict(
            sorted(Counter(annotation_candidates["candidate_group"]).items())
        ),
        "annotation_selection_policy": "2020+ periods, issuer-balanced rank, blinded recent packet",
        "annotation_packets": annotation_packets,
        "development_sha256": _hash_file(development_path),
        "private_holdout_sha256": _hash_file(holdout_path),
        "private_holdout_mode": oct(holdout_path.stat().st_mode & 0o777),
        "feature_snapshot_id": feature_report["data_snapshot_id"],
    }
    json_path = root / "manifest.json"
    markdown_path = root / "report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build IssuerRiskBench v1")
    parser.add_argument("--root", default="/artifacts/risk_data/issuer_risk_bench_v1")
    parser.add_argument(
        "--statement-root", default="/artifacts/risk_data/expansion_statements_v1"
    )
    parser.add_argument(
        "--pool-file",
        default="/artifacts/risk_data/expansion_pool_v1/expansion_pool_v1.json",
    )
    parser.add_argument("--feature-root", default="/artifacts/risk_data/features_v1")
    args = parser.parse_args()
    paths = build_benchmark(
        Path(args.root),
        statement_root=Path(args.statement_root),
        pool_file=Path(args.pool_file),
        feature_root=Path(args.feature_root),
    )
    print(json.dumps({"manifest": str(paths[0]), "report": str(paths[1])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
