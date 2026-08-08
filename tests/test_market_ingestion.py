import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

from financial_research_agent.config import Settings
from financial_research_agent.market.ingestion import MarketIngestionService
from financial_research_agent.market.normalize import normalize_daily_market
from financial_research_agent.market.repository import MarketDataRepository
from financial_research_agent.market.schema import BUSINESS_KEY, KLINE_DAILY_TABLE
from financial_research_agent.market.source import AkShareDailyMarketSource


def source_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "日期": ["2023-01-03", "2023-01-04"],
            "开盘": [100.0, 102.0],
            "收盘": [102.0, 101.0],
            "最高": [103.0, 104.0],
            "最低": [99.0, 100.0],
            "成交量": [1000, 1200],
            "成交额": [101000.0, 122000.0],
            "振幅": [4.0, 4.0],
            "涨跌幅": [2.0, -0.98],
            "涨跌额": [2.0, -1.0],
            "换手率": [1.2, 1.3],
        }
    )


def secondary_source_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2022-12-30", "2023-01-03", "2023-01-04"],
            "open": [99.0, 100.0, 102.0],
            "high": [101.0, 103.0, 104.0],
            "low": [98.0, 99.0, 100.0],
            "close": [100.0, 102.0, 101.0],
            "volume": [90000.0, 100000.0, 120000.0],
            "amount": [9000000.0, 10100000.0, 12200000.0],
            "outstanding_share": [10000000.0] * 3,
            "turnover": [0.009, 0.01, 0.012],
        }
    )


class FakeSource:
    name = "fake"
    endpoint = "daily_fixture"
    mapping_version = "fixture_v1"

    def fetch(self, symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
        return source_frame()


class FailingSource(FakeSource):
    def fetch(self, symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
        raise TimeoutError("source timeout")


class MarketNormalizationTests(unittest.TestCase):
    def test_invalid_ohlc_is_rejected(self) -> None:
        raw = source_frame()
        raw.loc[0, "最高"] = 98.0
        accepted, rejected, quality = normalize_daily_market(
            raw, "600519", "qfq", "fixture", "batch-1"
        )
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(quality.rejected_rows, 1)
        self.assertIn("invalid_high", rejected.iloc[0]["rejection_reasons"])

    def test_duplicate_business_key_is_rejected(self) -> None:
        raw = pd.concat([source_frame().iloc[[0]], source_frame().iloc[[0]]], ignore_index=True)
        accepted, rejected, _ = normalize_daily_market(
            raw, "600519", "qfq", "fixture", "batch-1"
        )
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 1)


class MarketSourceTests(unittest.TestCase):
    def test_akshare_source_retries_then_returns_data(self) -> None:
        client = Mock()
        client.stock_zh_a_hist.side_effect = [TimeoutError("temporary"), source_frame()]
        client.stock_zh_a_hist_tx.side_effect = TimeoutError("fallback temporary")
        source = AkShareDailyMarketSource(
            max_retries=2,
            retry_backoff_seconds=0.01,
            retry_max_backoff_seconds=0.01,
        )
        with patch.dict("sys.modules", {"akshare": client}), patch(
            "financial_research_agent.market.source.time.sleep"
        ) as sleep:
            result = source.fetch("600519", "20230101", "20230104", "qfq")
        self.assertEqual(len(result), 2)
        self.assertEqual(client.stock_zh_a_hist.call_count, 2)
        sleep.assert_called_once_with(0.01)

    def test_akshare_source_falls_back_to_tencent_and_normalizes_units(self) -> None:
        client = Mock()
        client.stock_zh_a_hist.side_effect = TimeoutError("primary unavailable")
        client.stock_zh_a_hist_tx.return_value = secondary_source_frame()
        source = AkShareDailyMarketSource(max_retries=0)
        with patch.dict("sys.modules", {"akshare": client}):
            result = source.fetch("601318", "20230101", "20230104", "qfq")
        self.assertEqual(list(result["成交量"]), [1000.0, 1200.0])
        self.assertEqual(result.attrs["source_endpoint"], "stock_zh_a_hist_tx")
        self.assertAlmostEqual(float(result.iloc[0]["换手率"]), 1.0)


class MarketIngestionTests(unittest.TestCase):
    def test_ingestion_is_incremental_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                iceberg_catalog_uri=f"sqlite:///{root}/catalog.db",
                iceberg_warehouse=f"file://{root}/warehouse",
                lake_root=str(root),
                market_stock_codes="600519",
                market_history_start="20230101",
            )
            service = MarketIngestionService(settings, FakeSource())
            first = service.run(end_date=date(2023, 1, 4))
            second = service.run(end_date=date(2023, 1, 4))
            table = service.repository.scan(KLINE_DAILY_TABLE).to_pandas()
            self.assertEqual(first["stocks"][0]["new_rows"], 2)
            self.assertEqual(second["stocks"][0]["status"], "up_to_date")
            self.assertEqual(len(table), 2)
            self.assertEqual(table.duplicated(BUSINESS_KEY).sum(), 0)
            queried = MarketDataRepository(settings).query_daily(
                "600519", date(2023, 1, 4), date(2023, 1, 4)
            )
            self.assertEqual(queried.num_rows, 1)

    def test_source_failure_is_reported_without_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                iceberg_catalog_uri=f"sqlite:///{root}/catalog.db",
                iceberg_warehouse=f"file://{root}/warehouse",
                lake_root=str(root),
                market_stock_codes="600519",
                market_history_start="20230101",
            )
            service = MarketIngestionService(settings, FailingSource())
            report = service.run(end_date=date(2023, 1, 4))
            self.assertEqual(report["status"], "warning")
            self.assertEqual(report["failed_stocks"][0]["stock_code"], "600519")
            self.assertEqual(service.repository.scan(KLINE_DAILY_TABLE).num_rows, 0)


if __name__ == "__main__":
    unittest.main()
