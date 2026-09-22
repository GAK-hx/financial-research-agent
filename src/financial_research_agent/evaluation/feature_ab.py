from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from financial_research_agent.evaluation.context_ab import _fixture
from financial_research_agent.evaluation.run import load_named_dataset
from financial_research_agent.memory.context import ContextBuilder
from financial_research_agent.memory.manager import MemoryManager
from financial_research_agent.memory.models import (
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySource,
    MemoryStatus,
)
from financial_research_agent.orchestration.interpreter import QueryInterpreter
from financial_research_agent.skills.registry import SkillRegistry


def _memory_record() -> MemoryRecord:
    now = datetime.now(timezone.utc)
    return MemoryRecord(
        memory_id=uuid4().hex,
        scope=MemoryScope(
            tenant_id="evaluation-ab",
            user_id="runner",
            session_id="memory-ab",
        ),
        kind=MemoryKind.SESSION,
        key="last_stock_codes",
        value=["600519"],
        version=1,
        status=MemoryStatus.ACTIVE,
        source=MemorySource(
            source_type="query_spec",
            source_id="evaluation-ab",
        ),
        created_at=now,
        updated_at=now,
    )


async def run() -> None:
    today = date(2026, 7, 15)
    interpreter = QueryInterpreter(today=today)
    registry = SkillRegistry.from_builtin_catalog()
    available_tools = {
        "market_query",
        "indicator_calculator",
        "financial_query",
        "stock_comparison",
        "report_candidate_search",
        "report_content_search",
    }

    holdout, holdout_hash = load_named_dataset("holdout")
    scorable = [case for case in holdout.cases if case.expected_success]
    skill_matches = 0
    selected_with_skill: list[dict[str, object]] = []
    for case in scorable:
        query = interpreter.interpret(case.question)
        selection = registry.select(query, available_tools)
        actual = sorted(selection.selected_ids)
        expected = sorted(case.expected_skills)
        matched = actual == expected
        skill_matches += int(matched)
        selected_with_skill.append(
            {
                "case_id": case.case_id,
                "expected": expected,
                "actual": actual,
                "matched": matched,
            }
        )

    memory_question = "继续分析它近3个月的走势"
    resolved, warnings = MemoryManager.resolve_question(
        memory_question, [_memory_record()]
    )
    memory_on_query = interpreter.interpret(resolved)
    memory_off_failed = False
    try:
        interpreter.interpret(memory_question)
    except ValueError:
        memory_off_failed = True

    query = interpreter.interpret("贵州茅台近3年营收和利润")
    selection = registry.select(query, available_tools)
    evidence = [_fixture(1000)]
    compression_results: list[dict[str, object]] = []
    for enabled in (False, True):
        built = await ContextBuilder(
            policy_version="financial_read_only_v1",
            compression_enabled=enabled,
        ).build_report(
            run_id=f"compression-ab-{enabled}",
            node_name="generate_report",
            query=query,
            evidence=evidence,
            selection=selection,
            memory=[],
        )
        compression_results.append(
            {
                "enabled": enabled,
                "token_estimate_before": (
                    built.manifest.token_estimate_before
                ),
                "token_estimate_after": (
                    built.manifest.token_estimate_after
                ),
                "compression_ratio": built.manifest.compression_ratio,
                "evidence_protection_passed": (
                    built.manifest.evidence_protection_passed
                ),
            }
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": holdout.dataset_version,
        "dataset_sha256": holdout_hash,
        "skill_ab": {
            "enabled_expected_match_rate": round(
                skill_matches / len(scorable), 4
            ),
            "disabled_selected_skill_count": 0,
            "disabled_effective_tool_count": len(available_tools),
            "cases": selected_with_skill,
        },
        "memory_ab": {
            "question": memory_question,
            "enabled_resolved_stock_codes": memory_on_query.stock_codes,
            "enabled_warnings": warnings,
            "disabled_reference_resolution_failed": memory_off_failed,
        },
        "compression_ab": compression_results,
    }
    target = Path(
        os.environ.get(
            "FEATURE_AB_OUTPUT",
            "/artifacts/agent_evaluation/feature_ab.json",
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
