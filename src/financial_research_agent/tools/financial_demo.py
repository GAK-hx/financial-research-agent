import asyncio
import json
from datetime import date

from financial_research_agent.config import get_settings
from financial_research_agent.tools.financial import FinancialQueryInput, FinancialQueryTool


async def run() -> None:
    result = await FinancialQueryTool(get_settings()).execute(
        "demo-financial",
        FinancialQueryInput(
            stock_code="600519",
            start_date=date(2024, 1, 1),
            end_date=date.today(),
        ),
    )
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    if not result.success:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(run())
