import json

from financial_research_agent.config import get_settings
from financial_research_agent.market.ingestion import MarketIngestionService
from financial_research_agent.market.source import AkShareDailyMarketSource


def main() -> None:
    settings = get_settings()
    source = AkShareDailyMarketSource(
        max_retries=settings.market_max_retries,
        retry_backoff_seconds=settings.market_retry_backoff_seconds,
        retry_max_backoff_seconds=settings.market_retry_max_backoff_seconds,
    )
    report = MarketIngestionService(settings, source).run()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["failed_stocks"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
