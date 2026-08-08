from datetime import date

import pyarrow as pa
from pyiceberg.expressions import And, EqualTo, GreaterThanOrEqual, LessThanOrEqual

from financial_research_agent.config import Settings
from financial_research_agent.market.schema import KLINE_DAILY_TABLE
from financial_research_agent.repositories.iceberg import IcebergRepository


class MarketDataRepository:
    def __init__(self, settings: Settings) -> None:
        self.repository = IcebergRepository(settings)

    def query_daily(self, stock_code: str, start_date: date, end_date: date) -> pa.Table:
        if len(stock_code) != 6 or not stock_code.isdigit():
            raise ValueError("stock_code must contain exactly six digits")
        if end_date < start_date:
            raise ValueError("end_date cannot be earlier than start_date")
        table = self.repository.catalog.load_table(KLINE_DAILY_TABLE)
        row_filter = And(
            EqualTo("stock_code", stock_code),
            And(
                GreaterThanOrEqual("trade_date", start_date),
                LessThanOrEqual("trade_date", end_date),
            ),
        )
        return table.scan(row_filter=row_filter).to_arrow()

    def current_snapshot_id(self) -> int | None:
        snapshot = self.repository.catalog.load_table(KLINE_DAILY_TABLE).current_snapshot()
        return snapshot.snapshot_id if snapshot else None
