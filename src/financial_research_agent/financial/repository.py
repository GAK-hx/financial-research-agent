from datetime import date

import pyarrow as pa
from pyiceberg.expressions import And, EqualTo, GreaterThanOrEqual, LessThanOrEqual

from financial_research_agent.config import Settings
from financial_research_agent.financial.schema import METRICS_TABLE
from financial_research_agent.repositories.iceberg import IcebergRepository


class FinancialDataRepository:
    def __init__(self, settings: Settings) -> None:
        self.repository = IcebergRepository(settings)

    def query_metrics(self, stock_code: str, start_date: date, end_date: date) -> pa.Table:
        if len(stock_code) != 6 or not stock_code.isdigit():
            raise ValueError("stock_code must contain exactly six digits")
        if end_date < start_date:
            raise ValueError("end_date cannot be earlier than start_date")
        table = self.repository.catalog.load_table(METRICS_TABLE)
        return table.scan(
            row_filter=And(
                EqualTo("stock_code", stock_code),
                And(
                    GreaterThanOrEqual("report_date", start_date),
                    LessThanOrEqual("report_date", end_date),
                ),
            )
        ).to_arrow()

    def current_snapshot_id(self) -> int | None:
        snapshot = self.repository.catalog.load_table(METRICS_TABLE).current_snapshot()
        return snapshot.snapshot_id if snapshot else None
