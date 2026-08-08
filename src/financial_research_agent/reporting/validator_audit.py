from __future__ import annotations

import argparse
import asyncio
import json

from financial_research_agent.config import get_settings
from financial_research_agent.domain.models import ReportClaim, ResearchReport
from financial_research_agent.orchestration.factory import build_orchestration_service
from financial_research_agent.reporting.validators import ReportValidator, evidence_data_as_of


async def run(question: str) -> None:
    settings = get_settings()
    orchestration = await build_orchestration_service(settings).run(question)
    if not orchestration.success or orchestration.query is None:
        print(json.dumps({"orchestration_errors": orchestration.errors}, ensure_ascii=False))
        raise SystemExit(1)
    report = ResearchReport(
        subjects=orchestration.query.stock_codes,
        summary="校验器验收草稿；不作为正式模型报告。",
        summary_evidence_ids=[
            item.evidence_id for item in orchestration.evidence
        ],
        claims=[
            ReportClaim(
                claim=item.statement,
                evidence_ids=[item.evidence_id],
                confidence="high" if item.evidence_type != "research_report" else "medium",
            )
            for item in orchestration.evidence
        ],
        risks=[
            {
                "risk": "本草稿仅用于验证真实Evidence的引用、数字和来源链。",
                "classification": "model_interpretation",
                "evidence_ids": [item.evidence_id for item in orchestration.evidence],
                "confidence": "low",
            }
        ],
        limitations=[
            {
                "limitation": "validation_only=true；未经过正式报告模型。",
                "category": "method",
                "evidence_ids": [],
            }
        ],
        data_as_of=evidence_data_as_of(orchestration.evidence),
    )
    validation = ReportValidator().validate(
        report,
        orchestration.query,
        orchestration.evidence,
        orchestration.run_id,
    )
    payload = {
        "validation_only": True,
        "run_id": orchestration.run_id,
        "evidence_count": len(orchestration.evidence),
        "data_as_of": report.data_as_of,
        "validation": validation.model_dump(mode="json"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    if not validation.passed:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a draft built from real Evidence statements")
    parser.add_argument(
        "question",
        nargs="?",
        default="分析宁德时代最近三年的营收、利润和盈利能力",
    )
    args = parser.parse_args()
    asyncio.run(run(args.question))


if __name__ == "__main__":
    main()
