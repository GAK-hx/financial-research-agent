import json

from financial_research_agent.config import get_settings
from financial_research_agent.financial.ingestion import FinancialIngestionService
from financial_research_agent.financial.source import AkShareFinancialStatementSource


def main() -> None:
    report = FinancialIngestionService(get_settings(), AkShareFinancialStatementSource()).run()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["failed_stocks"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
