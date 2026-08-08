from __future__ import annotations

import argparse
import asyncio
import json

from financial_research_agent.config import get_settings
from financial_research_agent.research import ResearchService


async def run(question: str) -> None:
    result = await ResearchService(get_settings()).analyze(question)
    reporting = result.reporting
    payload = {
        "success": result.success,
        "run_id": result.orchestration.run_id,
        "orchestration_success": result.orchestration.success,
        "planner_source": result.orchestration.planner_source,
        "evidence_count": len(result.orchestration.evidence),
        "evidence_ids_run_scoped": all(
            item.evidence_id.startswith(f"{result.orchestration.run_id}:")
            for item in result.orchestration.evidence
        ),
        "reporting_status": reporting.status if reporting else None,
        "report_attempts": reporting.attempts if reporting else 0,
        "validation": (
            reporting.validation.model_dump(mode="json")
            if reporting and reporting.validation
            else None
        ),
        "errors": reporting.errors if reporting else result.orchestration.errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not result.orchestration.success:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit the evidence-to-report boundary")
    parser.add_argument(
        "question",
        nargs="?",
        default="分析宁德时代最近三年的营收、利润和盈利能力",
    )
    args = parser.parse_args()
    asyncio.run(run(args.question))


if __name__ == "__main__":
    main()
