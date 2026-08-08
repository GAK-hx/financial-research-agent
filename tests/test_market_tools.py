import asyncio
import unittest
from datetime import date, timedelta

import pandas as pd
import pyarrow as pa
from pydantic import ValidationError

from financial_research_agent.config import Settings
from financial_research_agent.orchestration.registry import ToolRegistry
from financial_research_agent.tools.market import (
    IndicatorInput,
    IndicatorTool,
    MarketQueryInput,
    MarketQueryTool,
)


def market_table(rows: int = 20) -> pa.Table:
    start = date(2026, 1, 1)
    closes = [100.0 + index for index in range(rows)]
    return pa.Table.from_pandas(
        pd.DataFrame(
            {
                "stock_code": ["600519"] * rows,
                "trade_date": [start + timedelta(days=index) for index in range(rows)],
                "open": closes,
                "high": [value + 1 for value in closes],
                "low": [value - 1 for value in closes],
                "close": closes,
                "volume": [1000 + index for index in range(rows)],
                "amount": [100000.0 + index for index in range(rows)],
                "turnover_rate": [1.0] * rows,
            }
        ),
        preserve_index=False,
    )


class FakeMarketRepository:
    def __init__(self, table: pa.Table) -> None:
        self.table = table

    def query_daily(self, stock_code: str, start_date: date, end_date: date) -> pa.Table:
        return self.table

    def current_snapshot_id(self) -> int:
        return 12345


class MarketToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(market_stock_codes="600519,300750")

    def test_input_rejects_invalid_date_range_and_adjustment(self) -> None:
        with self.assertRaises(ValidationError):
            MarketQueryInput(
                stock_code="600519",
                start_date=date(2026, 2, 1),
                end_date=date(2026, 1, 1),
            )
        with self.assertRaises(ValidationError):
            MarketQueryInput(
                stock_code="600519",
                start_date=date(2026, 1, 1),
                end_date=date(2026, 2, 1),
                adjust_type="hfq",
            )

    def test_market_tool_discloses_actual_dates_and_locator(self) -> None:
        tool = MarketQueryTool(self.settings, FakeMarketRepository(market_table(2)))
        result = asyncio.run(
            tool.execute(
                "market-1",
                MarketQueryInput(
                    stock_code="600519",
                    start_date=date(2025, 12, 28),
                    end_date=date(2026, 1, 10),
                ),
            )
        )
        self.assertTrue(result.success)
        data = result.evidence[0].data
        self.assertEqual(data["actual_start"], "2026-01-01")
        self.assertEqual(data["actual_end"], "2026-01-02")
        self.assertIn("snapshot_id=12345", result.evidence[0].source.locator)

    def test_market_tool_enforces_stock_pool_and_row_limit(self) -> None:
        disallowed = MarketQueryTool(self.settings, FakeMarketRepository(market_table(1)))
        result = asyncio.run(
            disallowed.execute(
                "market-2",
                MarketQueryInput(
                    stock_code="000001",
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 1, 2),
                ),
            )
        )
        self.assertEqual(result.error_code, "STOCK_NOT_ALLOWED")
        oversized = MarketQueryTool(self.settings, FakeMarketRepository(market_table(1001)))
        result = asyncio.run(
            oversized.execute(
                "market-3",
                MarketQueryInput(
                    stock_code="600519",
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 1, 2),
                ),
            )
        )
        self.assertEqual(result.error_code, "MARKET_ROW_LIMIT")

    def test_indicator_fixed_sample(self) -> None:
        tool = IndicatorTool(self.settings, FakeMarketRepository(market_table(20)))
        result = asyncio.run(
            tool.execute(
                "indicator-1",
                IndicatorInput(
                    stock_code="600519",
                    start_date=date(2026, 1, 1),
                    end_date=date(2026, 1, 20),
                ),
            )
        )
        self.assertTrue(result.success)
        data = result.evidence[0].data
        self.assertAlmostEqual(data["period_return"], 0.19)
        self.assertAlmostEqual(data["ma5"], 117.0)
        self.assertAlmostEqual(data["ma20"], 109.5)
        self.assertAlmostEqual(data["max_drawdown"], 0.0)
        self.assertAlmostEqual(data["relative_volume_20d"], 1019 / 1009.5)
        self.assertAlmostEqual(data["period_high"], 120.0)
        self.assertAlmostEqual(data["period_low"], 99.0)
        self.assertAlmostEqual(data["annualized_volatility"], 0.007560634183932589)
        self.assertEqual(data["formula_version"], "market_indicators_v1")
        self.assertIn("input_locator", result.evidence[0].source.metadata)

    def test_tools_register_as_read_only_schemas(self) -> None:
        registry = ToolRegistry()
        registry.register(MarketQueryTool(self.settings, FakeMarketRepository(market_table(1))))
        registry.register(IndicatorTool(self.settings, FakeMarketRepository(market_table(1))))
        self.assertEqual({schema["name"] for schema in registry.schemas()}, {
            "market_query",
            "indicator_calculator",
        })


if __name__ == "__main__":
    unittest.main()
