from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from financial_research_agent.config import get_settings
from financial_research_agent.providers.model import build_model_provider
from financial_research_agent.risk.team_runtime import BenchmarkTeamRuntime


def _select_latest_multi_domain_case(
    candidates_path: Path, features_path: Path
) -> tuple[str, str, dict[str, Any]]:
    candidates = pq.read_table(candidates_path).to_pylist()
    eligible = [
        row
        for row in candidates
        if str(row.get("status")) in {"watch", "escalate"}
    ]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in eligible:
        key = (str(row["issuer_id"]), str(row["report_period"]))
        groups.setdefault(key, []).append(row)
    if not groups:
        raise ValueError("risk candidate table has no watch/escalate rows")
    issuer_id, report_period = max(
        groups,
        key=lambda key: (
            len({str(row["risk_category"]) for row in groups[key]}),
            key[1],
            key[0],
        ),
    )
    selected = groups[(issuer_id, report_period)]
    triggered = {
        metric
        for row in selected
        for metric in json.loads(str(row["triggered_metrics_json"]))
    }
    features = [
        row
        for row in pq.read_table(features_path).to_pylist()
        if str(row["issuer_id"]) == issuer_id
        and str(row["report_period"]) == report_period
        and str(row["metric_code"]) in triggered
    ]
    context = {
        "point_in_time": {
            "issuer_id": issuer_id,
            "report_period": report_period,
            "as_of_date": str(selected[0]["as_of_date"]),
            "data_snapshot_id": str(selected[0]["data_snapshot_id"]),
        },
        "risk_candidates": [
            {
                "candidate_id": str(row["candidate_id"]),
                "category": str(row["risk_category"]),
                "status": str(row["status"]),
                "rule_score": row.get("rule_score"),
                "triggered_metrics": json.loads(str(row["triggered_metrics_json"])),
                "evidence_ids": json.loads(str(row["evidence_ids_json"])),
            }
            for row in selected
        ],
        "risk_features": [
            {
                "metric_code": str(row["metric_code"]),
                "value": row.get("value"),
                "unit": str(row.get("unit") or ""),
                "availability": str(row["availability"]),
                "periods_used": int(row["periods_used"]),
                "source_fact_ids": json.loads(str(row["source_fact_ids_json"])),
            }
            for row in features
        ],
        "usage_policy": (
            "These are deterministic point-in-time candidates, not labels. Review support, "
            "counterevidence and missing information; do not infer bankruptcy or investment advice."
        ),
    }
    return issuer_id, report_period, context


async def run_smoke(
    *, candidates_path: Path, features_path: Path, output_root: Path
) -> dict[str, Any]:
    issuer_id, report_period, context = _select_latest_multi_domain_case(
        candidates_path, features_path
    )
    categories = sorted(
        {str(row["category"]) for row in context["risk_candidates"]}
    )
    provider = build_model_provider(get_settings())
    runtime = BenchmarkTeamRuntime(provider)
    try:
        state = await runtime.run(
            benchmark="risk_demo",
            case_id=f"risk-demo:{issuer_id}:{report_period}",
            question=(
                f"Review the point-in-time financial risk candidates for issuer {issuer_id} "
                f"at report period {report_period}. Confirm, qualify or reject only the supplied "
                "candidate domains and summarize the evidence limitations."
            ),
            controlled_context=context,
            task_metadata={
                "candidate_categories": categories,
                "candidate_count": len(context["risk_candidates"]),
                "has_table": False,
                "has_text": False,
                "context_preview": json.dumps(
                    context["risk_candidates"], ensure_ascii=False
                )[:2400],
            },
        )
    finally:
        await provider.aclose()
    result = {
        "status": "PASS",
        "model": get_settings().model_name,
        "case_id": f"risk-demo:{issuer_id}:{report_period}",
        "business_data_used_for_accuracy_benchmark": False,
        "candidate_categories": categories,
        "team_plan": state["team_plan"],
        "agent_runs": state["agent_runs"],
        "evaluations": state["evaluations"],
        "artifact": state["artifact"],
        "node_trace": state["node_trace"],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    plan_roles = [agent["role"] for agent in state["team_plan"]["agents"]]
    findings = state["artifact"]["risks"]
    (output_root / "report.md").write_text(
        "\n".join(
            [
                "# 风险专用子 Agent 最小演示",
                "",
                "- 用途：仅验证真实业务数据上的编排与产物，不作为准确率 Benchmark；",
                f"- Case：`risk-demo:{issuer_id}:{report_period}`；",
                f"- 候选域：{', '.join(categories)}；",
                f"- Supervisor 选择：{', '.join(plan_roles)}；",
                f"- Evaluator：`{state['artifact']['evaluation']['decision']}`；",
                f"- 修复次数：{state['artifact']['scorecard']['repair_count']}；",
                f"- 数据截止：`{state['artifact']['as_of_date']}`；",
                f"- 数据快照：`{state['artifact']['data_snapshot_id']}`；",
                "",
                "## 结构化风险结论",
                "",
                *[
                    (
                        f"- `{item['category']}`（{item['candidate_status']}，"
                        f"severity={item['severity']}，confidence={item['confidence']:.2f}，"
                        f"accepted={str(item['accepted']).lower()}）：{item['conclusion']}"
                    )
                    for item in findings
                ],
                "",
                "## 最终回答",
                "",
                str(state["artifact"]["answer"]),
                "",
            ]
        ),
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one risk-domain Agent team smoke")
    parser.add_argument(
        "--candidates",
        default="/artifacts/phase5_step01/features_v1/risk_candidates.parquet",
    )
    parser.add_argument(
        "--features",
        default="/artifacts/phase5_step01/features_v1/risk_features.parquet",
    )
    parser.add_argument(
        "--output-root",
        default="/artifacts/phase5_step02/risk_team_smoke_v1",
    )
    args = parser.parse_args()
    result = asyncio.run(
        run_smoke(
            candidates_path=Path(args.candidates),
            features_path=Path(args.features),
            output_root=Path(args.output_root),
        )
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "case_id": result["case_id"],
                "candidate_categories": result["candidate_categories"],
                "selected_roles": [
                    agent["role"] for agent in result["team_plan"]["agents"]
                ],
                "output_root": str(args.output_root),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
