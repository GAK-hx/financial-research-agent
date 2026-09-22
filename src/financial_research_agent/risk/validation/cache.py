from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from financial_research_agent.config import Settings
from financial_research_agent.retrieval.coordinator import InMemoryRetrievalCoordinator
from financial_research_agent.risk.agents.agent_models import (
    AgentScorecard,
    EvaluationDecision,
    RiskAssessmentArtifact,
    SubAgentEvaluation,
)
from financial_research_agent.risk.agents.artifact_cache import RiskArtifactCache


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


def _contexts(path: Path, limit: int = 20) -> dict[str, dict[str, Any]]:
    rows = pq.read_table(path).to_pylist()
    by_issuer: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_issuer.setdefault(str(row["issuer_id"]), []).append(row)
    selected: dict[str, dict[str, Any]] = {}
    for issuer_id in sorted(by_issuer):
        issuer_rows = by_issuer[issuer_id]
        useful = [
            row
            for row in issuer_rows
            if str(row["status"]) in {"watch", "escalate"}
        ]
        if not useful:
            continue
        report_period = max(row["report_period"] for row in useful)
        period_rows = [
            row for row in issuer_rows if row["report_period"] == report_period
        ]
        first = period_rows[0]
        selected[issuer_id] = {
            "point_in_time": {
                "issuer_id": issuer_id,
                "report_period": str(report_period),
                "as_of_date": str(first["as_of_date"]),
                "data_snapshot_id": str(first["data_snapshot_id"]),
            },
            "risk_candidates": [
                {
                    "candidate_id": str(row["candidate_id"]),
                    "category": str(row["risk_category"]),
                    "status": str(row["status"]),
                    "rule_score": row.get("rule_score"),
                    "triggered_metrics_json": str(row["triggered_metrics_json"]),
                    "evidence_ids_json": str(row["evidence_ids_json"]),
                }
                for row in period_rows
            ],
            "risk_features": [],
        }
        if len(selected) == limit:
            break
    if len(selected) < limit:
        raise ValueError(f"only {len(selected)} eligible issuers; need {limit}")
    return selected


def _assignments(issuers: list[str], users: int) -> dict[str, list[str]]:
    common = issuers[:3]
    rotating = issuers[3:]
    return {
        f"user-{index:02d}": [
            *common,
            rotating[(2 * index) % len(rotating)],
            rotating[(2 * index + 1) % len(rotating)],
        ]
        for index in range(users)
    }


def _frozen_artifact(context: dict[str, Any]) -> RiskAssessmentArtifact:
    point = context["point_in_time"]
    statuses = Counter(row["status"] for row in context["risk_candidates"])
    answer = ", ".join(f"{key}={value}" for key, value in sorted(statuses.items()))
    return RiskAssessmentArtifact(
        benchmark="risk_demo",
        case_id=f"risk-cache:{point['issuer_id']}:{point['report_period']}",
        subject_id=point["issuer_id"],
        report_period=point["report_period"],
        as_of_date=point["as_of_date"],
        data_snapshot_id=point["data_snapshot_id"],
        answer=answer,
        limitations=["Frozen response for concurrency and cache validation only."],
        evaluation=SubAgentEvaluation(
            decision=EvaluationDecision.ACCEPT_WITH_LIMITATIONS,
            accepted_agent_ids=["frozen-risk-analyzer"],
        ),
        scorecard=AgentScorecard(
            benchmark="risk_demo",
            case_id=f"risk-cache:{point['issuer_id']}:{point['report_period']}",
            decision=EvaluationDecision.ACCEPT_WITH_LIMITATIONS,
            repair_count=0,
            contributions=[],
            total_tool_calls=0,
            total_tokens=0,
            total_latency_seconds=0,
        ),
    )


async def _run_queries(
    cache: RiskArtifactCache,
    contexts: dict[str, dict[str, Any]],
    assignments: dict[str, list[str]],
    calls: Counter[str],
    *,
    phase: str,
) -> tuple[list[dict[str, Any]], list[float]]:
    async def one(user_id: str, issuer_id: str) -> dict[str, Any]:
        context = contexts[issuer_id]
        point = context["point_in_time"]

        async def compute() -> RiskAssessmentArtifact:
            calls[issuer_id] += 1
            await asyncio.sleep(0.015)
            return _frozen_artifact(context)

        started = time.perf_counter()
        run_id = f"{phase}:{user_id}:{issuer_id}"
        result = await cache.get_or_compute(
            run_id=run_id,
            subject_id=issuer_id,
            report_period=point["report_period"],
            as_of_date=point["as_of_date"],
            data_snapshot_id=point["data_snapshot_id"],
            controlled_context=context,
            compute=compute,
        )
        report = cache.present(
            result,
            run_id=run_id,
            tenant_id=f"tenant-{user_id}",
            user_id=user_id,
            session_id=f"session-{user_id}",
            requested_dimensions=["liquidity", "earnings_quality"],
            narrative=f"{user_id} requested a scoped presentation for {issuer_id}.",
        )
        latency_ms = (time.perf_counter() - started) * 1000
        return {
            "user_id": user_id,
            "issuer_id": issuer_id,
            "decision": result.decision,
            "artifact_id": result.artifact.artifact_id,
            "public_payload": result.artifact.payload,
            "report": report.model_dump(mode="json"),
            "latency_ms": latency_ms,
        }

    rows = await asyncio.gather(
        *(
            one(user_id, issuer_id)
            for user_id, issuer_ids in assignments.items()
            for issuer_id in issuer_ids
        )
    )
    return rows, [row["latency_ms"] for row in rows]


def _scope_leaks(rows: list[dict[str, Any]]) -> int:
    identities = {
        token
        for row in rows
        for token in (
            row["user_id"],
            f"tenant-{row['user_id']}",
            f"session-{row['user_id']}",
        )
    }
    return sum(
        1
        for row in rows
        if any(
            identity in json.dumps(row["public_payload"], ensure_ascii=False)
            for identity in identities
        )
    )


async def _level(
    contexts: dict[str, dict[str, Any]], users: int
) -> dict[str, Any]:
    coordinator = InMemoryRetrievalCoordinator(
        Settings(retrieval_join_timeout_seconds=5, retrieval_join_poll_seconds=0.05)
    )
    cache = RiskArtifactCache(
        coordinator,
        model_id="deepseek-flash",
        skill_versions=["risk-domain-team@1.0.0", "risk-evaluator@1.0.0"],
    )
    assignments = _assignments(list(contexts), users)
    unique_issuers = set().union(*map(set, assignments.values()))
    calls: Counter[str] = Counter()
    cold_rows, cold_latency = await _run_queries(
        cache, contexts, assignments, calls, phase=f"cold-{users}"
    )
    cold_calls = sum(calls.values())
    warm_rows, warm_latency = await _run_queries(
        cache, contexts, assignments, calls, phase=f"warm-{users}"
    )
    warm_calls = sum(calls.values()) - cold_calls
    cold_p95 = _percentile(cold_latency, 0.95)
    warm_p95 = _percentile(warm_latency, 0.95)
    return {
        "users": users,
        "queries": users * 5,
        "unique_issuers": len(unique_issuers),
        "configured_common_share_per_user": 0.6,
        "cold": {
            "analysis_calls": cold_calls,
            "reuse_ratio": round(1 - cold_calls / (users * 5), 4),
            "p50_ms": _percentile(cold_latency, 0.50),
            "p95_ms": cold_p95,
            "p99_ms": _percentile(cold_latency, 0.99),
            "decisions": dict(Counter(row["decision"] for row in cold_rows)),
        },
        "warm": {
            "analysis_calls": warm_calls,
            "reuse_ratio": round(1 - warm_calls / (users * 5), 4),
            "p50_ms": _percentile(warm_latency, 0.50),
            "p95_ms": warm_p95,
            "p99_ms": _percentile(warm_latency, 0.99),
            "decisions": dict(Counter(row["decision"] for row in warm_rows)),
        },
        "warm_p95_reduction": round(
            (cold_p95 - warm_p95) / cold_p95 if cold_p95 else 0.0, 4
        ),
        "public_payload_scope_leaks": _scope_leaks([*cold_rows, *warm_rows]),
        "artifact_consistency_failures": sum(
            1
            for issuer_id in unique_issuers
            if len(
                {
                    row["artifact_id"]
                    for row in [*cold_rows, *warm_rows]
                    if row["issuer_id"] == issuer_id
                }
            )
            != 1
        ),
    }


async def _incremental(contexts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    coordinator = InMemoryRetrievalCoordinator(
        Settings(retrieval_join_timeout_seconds=5, retrieval_join_poll_seconds=0.05)
    )
    cache = RiskArtifactCache(
        coordinator,
        model_id="deepseek-flash",
        skill_versions=["risk-domain-team@1.0.0", "risk-evaluator@1.0.0"],
    )
    assignments = _assignments(list(contexts), 5)
    calls: Counter[str] = Counter()
    await _run_queries(cache, contexts, assignments, calls, phase="incremental-base")
    baseline_calls = calls.copy()
    changed = list(contexts)[:2]
    updated = {issuer: json.loads(json.dumps(context, default=str)) for issuer, context in contexts.items()}
    for issuer in changed:
        updated[issuer]["point_in_time"]["data_snapshot_id"] += ":incremental-v2"
        updated[issuer]["risk_candidates"][0]["incremental_marker"] = "new-public-data"
    rows, latency = await _run_queries(
        cache, updated, assignments, calls, phase="incremental-update"
    )
    incremental_calls = sum(calls.values()) - sum(baseline_calls.values())
    return {
        "changed_issuers": changed,
        "expected_recomputed": len(changed),
        "actual_recomputed": incremental_calls,
        "unaffected_recomputed": sum(
            calls[issuer] - baseline_calls[issuer]
            for issuer in contexts
            if issuer not in changed
        ),
        "p95_ms": _percentile(latency, 0.95),
        "decisions": dict(Counter(row["decision"] for row in rows)),
        "public_payload_scope_leaks": _scope_leaks(rows),
    }


async def run_validation(candidates: Path, output_root: Path) -> dict[str, Any]:
    contexts = _contexts(candidates)
    levels = [await _level(contexts, users) for users in (1, 5, 20, 50)]
    incremental = await _incremental(contexts)
    checks = {
        "cold_single_flight": all(
            level["cold"]["analysis_calls"] == level["unique_issuers"]
            for level in levels
        ),
        "warm_zero_analysis_calls": all(
            level["warm"]["analysis_calls"] == 0 for level in levels
        ),
        "warm_latency_materially_lower": all(
            level["warm_p95_reduction"] >= 0.50 for level in levels
        ),
        "public_user_scope_leaks_zero": all(
            level["public_payload_scope_leaks"] == 0 for level in levels
        )
        and incremental["public_payload_scope_leaks"] == 0,
        "artifact_identity_consistent": all(
            level["artifact_consistency_failures"] == 0 for level in levels
        ),
        "incremental_only_changed_recomputed": incremental["actual_recomputed"]
        == incremental["expected_recomputed"]
        and incremental["unaffected_recomputed"] == 0,
    }
    report = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "validation": "risk_artifact_cache",
        "execution_mode": "docker_frozen_response_semantic_validation",
        "accuracy_claimed": False,
        "latency_scope": "in_process_frozen_response_only",
        "model_identity_for_cache": "deepseek-flash",
        "candidate_source": str(candidates),
        "issuer_pool_size": len(contexts),
        "levels": levels,
        "incremental": incremental,
        "checks": checks,
        "notes": [
            "This program validates risk-domain cache semantics, not model quality.",
            "PostgreSQL, Redis, and Spring restart safety is validated by the gateway suite.",
            "Latency values must not be presented as production API latency.",
        ],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# 风险公共产物与多用户缓存验证",
        "",
        f"- 状态：`{report['status']}`；",
        "- 模式：Docker 内冻结响应语义测试，不调用模型、不报告准确率；",
        "- 范围：公共风险分析复用、分析 single-flight、用户展示隔离、增量失效；",
        "- 后端故障恢复与队列安全由 Gateway 集成验证覆盖。",
        "",
        "## 1/5/20/50 用户结果",
        "",
        "| 用户 | 查询 | 唯一公司 | 冷态分析调用 | 热态分析调用 | 冷态p95(ms) | 热态p95(ms) | p95下降 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for level in levels:
        lines.append(
            f"| {level['users']} | {level['queries']} | {level['unique_issuers']} | "
            f"{level['cold']['analysis_calls']} | {level['warm']['analysis_calls']} | "
            f"{level['cold']['p95_ms']:.3f} | {level['warm']['p95_ms']:.3f} | "
            f"{level['warm_p95_reduction']:.1%} |"
        )
    lines.extend(
        [
            "",
            "## 增量失效",
            "",
            f"- 变化公司：{', '.join(incremental['changed_issuers'])}；",
            f"- 预期/实际重算：{incremental['expected_recomputed']}/"
            f"{incremental['actual_recomputed']}；",
            f"- 未变化公司误重算：{incremental['unaffected_recomputed']}；",
            "",
            "## 验收",
            "",
            *[
                f"- [{'x' if passed else ' '}] `{name}`"
                for name, passed in checks.items()
            ],
            "",
            "延迟仅用于本轮同环境相对比较，不作为生产API性能数字。",
            "",
        ]
    )
    (output_root / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate risk artifact caching and reuse")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(run_validation(args.candidates, args.output_root))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
