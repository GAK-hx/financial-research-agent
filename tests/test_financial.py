import asyncio
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa

from financial_research_agent.config import Settings
from financial_research_agent.financial.ingestion import FinancialIngestionService
from financial_research_agent.financial.normalize import calculate_metrics, normalize_statement
from financial_research_agent.financial.schema import METRICS_TABLE
from financial_research_agent.orchestration.registry import ToolRegistry
from financial_research_agent.tools.financial import FinancialQueryInput, FinancialQueryTool

DATES = ["20241231", "20250331", "20251231", "20260331"]


def common_fields() -> dict:
    return {
        "报告日": DATES,
        "公告日期": ["20250301", "20250420", "20260301", "20260420"],
        "币种": ["CNY"] * 4,
        "类型": ["合并期末"] * 4,
    }


def income_raw() -> pd.DataFrame:
    return pd.DataFrame(
        {
            **common_fields(),
            "营业收入": [100.0, 30.0, 120.0, 36.0],
            "营业成本": [50.0, 15.0, 60.0, 18.0],
            "归属于母公司所有者的净利润": [15.0, 5.0, 20.0, 6.0],
        }
    )


def balance_raw() -> pd.DataFrame:
    return pd.DataFrame(
        {
            **common_fields(),
            "资产总计": [160.0, 170.0, 180.0, 200.0],
            "负债合计": [60.0, 65.0, 60.0, 60.0],
            "归属于母公司股东权益合计": [100.0, 105.0, 120.0, 140.0],
        }
    )


def cash_flow_raw() -> pd.DataFrame:
    return pd.DataFrame(
        {**common_fields(), "经营活动产生的现金流量净额": [18.0, 4.0, 25.0, 8.0]}
    )


class FakeFinancialSource:
    name = "fake"
    endpoint = "financial_fixture"
    mapping_version = "fixture_v1"

    def fetch(self, stock_code: str, statement: str) -> pd.DataFrame:
        return {"income": income_raw, "balance": balance_raw, "cash_flow": cash_flow_raw}[
            statement
        ]()


class FakeFinancialRepository:
    def __init__(self, table: pa.Table) -> None:
        self.table = table

    def query_metrics(self, stock_code: str, start_date: date, end_date: date) -> pa.Table:
        return self.table

    def current_snapshot_id(self) -> int:
        return 67890


class FinancialTests(unittest.TestCase):
    def test_metrics_formulas_and_missing_yoy(self) -> None:
        income, _, = normalize_statement(income_raw(), "income", "600519", "fake", "i")
        balance, _, = normalize_statement(balance_raw(), "balance", "600519", "fake", "b")
        cash_flow, _, = normalize_statement(cash_flow_raw(), "cash_flow", "600519", "fake", "c")
        metrics = calculate_metrics(income, balance, cash_flow, "m", "fake")
        q1_2026 = metrics.loc[metrics["report_date"] == date(2026, 3, 31)].iloc[0]
        q1_2025 = metrics.loc[metrics["report_date"] == date(2025, 3, 31)].iloc[0]
        self.assertAlmostEqual(q1_2026["revenue_yoy"], 0.2)
        self.assertAlmostEqual(q1_2026["parent_net_profit_yoy"], 0.2)
        self.assertAlmostEqual(q1_2026["gross_margin"], 0.5)
        self.assertAlmostEqual(q1_2026["debt_ratio"], 0.3)
        self.assertAlmostEqual(q1_2026["roe_period"], 6 / 130)
        self.assertIsNone(q1_2025["revenue_yoy"])

    def test_ingestion_writes_four_tables_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                iceberg_catalog_uri=f"sqlite:///{root}/catalog.db",
                iceberg_warehouse=f"file://{root}/warehouse",
                lake_root=str(root),
                market_stock_codes="600519",
            )
            service = FinancialIngestionService(settings, FakeFinancialSource())
            first = service.run()
            second = service.run()
            self.assertEqual(first["stocks"][0]["metrics"]["new_rows"], 4)
            self.assertEqual(second["stocks"][0]["metrics"]["new_rows"], 0)
            self.assertEqual(service.repository.scan(METRICS_TABLE).num_rows, 4)

    def test_financial_tool_evidence_and_registry_admission(self) -> None:
        income, _ = normalize_statement(income_raw(), "income", "600519", "fake", "i")
        balance, _ = normalize_statement(balance_raw(), "balance", "600519", "fake", "b")
        cash_flow, _ = normalize_statement(cash_flow_raw(), "cash_flow", "600519", "fake", "c")
        metrics = calculate_metrics(income, balance, cash_flow, "m", "fake")
        tool = FinancialQueryTool(
            Settings(market_stock_codes="600519"),
            FakeFinancialRepository(pa.Table.from_pandas(metrics, preserve_index=False)),
        )
        result = asyncio.run(
            tool.execute(
                "financial-1",
                FinancialQueryInput(
                    stock_code="600519",
                    start_date=date(2024, 1, 1),
                    end_date=date(2026, 12, 31),
                ),
            )
        )
        self.assertTrue(result.success)
        self.assertEqual(result.evidence[0].data["period_count"], 4)
        self.assertEqual(result.evidence[0].data["formula_version"], "financial_metrics_v1")
        self.assertIn("snapshot_id=67890", result.evidence[0].source.locator)
        registry = ToolRegistry()
        registry.register(tool)
        self.assertEqual(registry.schemas()[0]["name"], "financial_query")


if __name__ == "__main__":
    unittest.main()
