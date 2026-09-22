from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from time import perf_counter

from financial_research_agent.domain.models import (
    Evidence,
    Intent,
    QuerySpec,
    SourceReference,
)
from financial_research_agent.memory.context import ContextBuilder
from financial_research_agent.skills.registry import SkillRegistry


def _fixture(rows: int) -> Evidence:
    return Evidence(
        evidence_id="context-ab:financial-1",
        evidence_type="financial",
        subject="600519",
        statement="600519最新营业收入为100亿元，报告期为2025年。",
        data={
            "snapshot_id": 12,
            "formula_version": "financial_metrics_v1",
            "data_as_of": "2025-12-31",
            "rows": [
                {"period": f"period-{index:04d}", "revenue": index * 10}
                for index in range(rows)
            ],
        },
        source=SourceReference(
            source_type="iceberg",
            locator="iceberg://financial.metrics?snapshot_id=12",
            observed_at=datetime.now(timezone.utc),
            metadata={
                "snapshot_id": 12,
                "table": "financial.metrics",
            },
        ),
    )


async def run() -> None:
    rows = int(os.environ.get("CONTEXT_AB_ROWS", "1000"))
    repeats = int(os.environ.get("CONTEXT_AB_REPEATS", "100"))
    query = QuerySpec(
        stock_codes=["600519"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        intent=Intent.FINANCIAL,
    )
    registry = SkillRegistry.from_builtin_catalog()
    selection = registry.select(
        query,
        {
            "market_query",
            "indicator_calculator",
            "financial_query",
            "stock_comparison",
            "report_candidate_search",
            "report_content_search",
        },
    )
    evidence = [_fixture(rows)]
    results: list[dict[str, object]] = []
    for compression_enabled in (False, True):
        builder = ContextBuilder(
            policy_version="context_policy_v1",
            compression_enabled=compression_enabled,
        )
        built = None
        started = perf_counter()
        for index in range(repeats):
            built = await builder.build_report(
                run_id=f"context-ab-{compression_enabled}-{index}",
                node_name="generate_report",
                query=query,
                evidence=evidence,
                selection=selection,
                memory=[],
            )
        elapsed_ms = (perf_counter() - started) * 1000
        assert built is not None
        manifest = built.manifest
        results.append(
            {
                "compression_enabled": compression_enabled,
                "rows": rows,
                "repeats": repeats,
                "token_estimate_before": manifest.token_estimate_before,
                "token_estimate_after": manifest.token_estimate_after,
                "compression_ratio": round(manifest.compression_ratio, 6),
                "mean_build_ms": round(elapsed_ms / repeats, 3),
                "evidence_protection_passed": (
                    manifest.evidence_protection_passed
                ),
                "summary_depth": manifest.summary_depth,
                "warnings": manifest.warnings,
            }
        )
    payload = {
        "fixture": "same structured Evidence with bulk rows",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }
    target = Path(
        os.environ.get(
            "CONTEXT_AB_OUTPUT",
            "/artifacts/phase2_step06/context_gate/context_ab.json",
        )
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"output": str(target), **payload}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(run())
