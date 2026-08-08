import asyncio
import json
from datetime import date

from financial_research_agent.config import get_settings
from financial_research_agent.tools.market import (
    IndicatorInput,
    IndicatorTool,
    MarketQueryInput,
    MarketQueryTool,
)


async def run() -> None:
    settings = get_settings()
    start = date(2026, 1, 1)
    end = date.today()
    market = await MarketQueryTool(settings).execute(
        "demo-market",
        MarketQueryInput(stock_code="600519", start_date=start, end_date=end),
    )
    indicator = await IndicatorTool(settings).execute(
        "demo-indicator",
        IndicatorInput(stock_code="600519", start_date=start, end_date=end),
    )
    payload = {
        "market": market.model_dump(mode="json", exclude={"evidence": {0: {"data": {"rows"}}}}),
        "indicator": indicator.model_dump(mode="json"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not market.success or not indicator.success:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(run())
