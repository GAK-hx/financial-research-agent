from __future__ import annotations

import asyncio
import json
from pathlib import Path

from financial_research_agent.config import get_settings
from financial_research_agent.domain.models import Evidence, QuerySpec, ResearchReport
from financial_research_agent.providers.model import OpenAICompatibleProvider
from financial_research_agent.reporting.reporter import EvidenceOnlyReporter
from financial_research_agent.reporting.validators import ReportValidator


async def run() -> None:
    settings = get_settings()
    artifact_path = Path(settings.artifacts_root) / "model_runs/deepseek_flash_market.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    response = artifact["response"]
    query = QuerySpec.model_validate(response["query_spec"])
    evidence = [Evidence.model_validate(item) for item in response["evidence"]]
    original = ResearchReport.model_validate(response["report"])
    broken_claim = original.claims[0].model_copy(
        update={"claim": "贵州茅台区间收益率为99.0%。"}
    )
    broken = original.model_copy(update={"claims": [broken_claim, *original.claims[1:]]})
    validator = ReportValidator()
    before = validator.validate(broken, query, evidence, response["run_id"])
    if before.passed or not any("NUMERIC_UNSUPPORTED" in error for error in before.errors):
        raise RuntimeError("failed to construct the invalid revision draft")
    repaired = await EvidenceOnlyReporter(
        settings, OpenAICompatibleProvider(settings)
    ).generate(
        artifact["question"],
        query,
        evidence,
        draft=broken,
        validation_errors=before.errors,
    )
    after = validator.validate(repaired, query, evidence, response["run_id"])
    output = {
        "model": settings.model_name,
        "source_run_id": response["run_id"],
        "before_passed": before.passed,
        "before_errors": before.errors,
        "revision_calls": 1,
        "after_passed": after.passed,
        "after_errors": after.errors,
        "repaired_claim": repaired.claims[0].claim,
    }
    result_path = Path(settings.artifacts_root) / "model_runs/deepseek_flash_revision.json"
    result_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({**output, "artifact": str(result_path)}, ensure_ascii=False, indent=2))
    if not after.passed:
        raise RuntimeError("real model revision did not pass validation")


if __name__ == "__main__":
    asyncio.run(run())
