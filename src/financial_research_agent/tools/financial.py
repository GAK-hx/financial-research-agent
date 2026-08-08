from __future__ import annotations

import hashlib
import time
from datetime import date, datetime, timezone

import pandas as pd
from pydantic import BaseModel, Field, model_validator

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import Evidence, SourceReference, ToolResult
from financial_research_agent.financial.normalize import FORMULA_VERSION
from financial_research_agent.financial.repository import FinancialDataRepository
from financial_research_agent.financial.schema import METRICS_TABLE
from financial_research_agent.tools.base import FinancialTool, ToolDefinition

MAX_FINANCIAL_PERIODS = 40


class FinancialQueryInput(BaseModel):
    stock_code: str = Field(pattern=r"^\d{6}$")
    start_date: date
    end_date: date
    max_periods: int = Field(default=20, ge=1, le=MAX_FINANCIAL_PERIODS)

    @model_validator(mode="after")
    def validate_dates(self) -> FinancialQueryInput:
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date")
        return self


class FinancialPeriod(BaseModel):
    report_date: date
    source_announcement_date: date | None
    currency: str | None
    statement_scope: str | None
    revenue: float | None
    parent_net_profit: float | None
    operating_cash_flow: float | None
    revenue_yoy: float | None
    parent_net_profit_yoy: float | None
    gross_margin: float | None
    debt_ratio: float | None
    roe_period: float | None


class FinancialQueryOutput(BaseModel):
    stock_code: str
    requested_start: date
    requested_end: date
    actual_start: date
    actual_end: date
    data_as_of: date
    periods: list[FinancialPeriod]
    period_count: int
    formula_version: str
    snapshot_id: int | None
    point_in_time_eligible: bool = False
    data_limitations: list[str] = Field(default_factory=list)


class FinancialQueryTool(FinancialTool):
    definition = ToolDefinition(
        name="financial_query",
        version="1.0.0",
        description="Read curated financial metrics by stock and reporting period.",
        timeout_seconds=15,
        max_rows=MAX_FINANCIAL_PERIODS,
        data_domain="financial",
    )
    input_model = FinancialQueryInput

    def __init__(self, settings: Settings, repository: FinancialDataRepository | None = None) -> None:
        self.settings = settings
        self.repository = repository or FinancialDataRepository(settings)

    async def execute(self, task_id: str, arguments: FinancialQueryInput) -> ToolResult:
        started = time.perf_counter()
        if arguments.stock_code not in self.settings.stock_codes:
            return self._error(task_id, started, "STOCK_NOT_ALLOWED", "stock is outside configured pool")
        table = self.repository.query_metrics(
            arguments.stock_code, arguments.start_date, arguments.end_date
        )
        if table.num_rows == 0:
            return self._error(task_id, started, "FINANCIAL_DATA_EMPTY", "no financial periods found")
        if table.num_rows > arguments.max_periods:
            return self._error(
                task_id,
                started,
                "FINANCIAL_PERIOD_LIMIT",
                f"query returned {table.num_rows} periods; maximum is {arguments.max_periods}",
            )
        frame = table.to_pandas().sort_values("report_date")
        frame = frame.astype(object).where(pd.notna(frame), None)
        snapshot_id = self.repository.current_snapshot_id()
        periods = [
            FinancialPeriod.model_validate(
                {**row, "source_announcement_date": row.pop("announcement_date", None)}
            )
            for row in frame.to_dict("records")
        ]
        output = FinancialQueryOutput(
            stock_code=arguments.stock_code,
            requested_start=arguments.start_date,
            requested_end=arguments.end_date,
            actual_start=periods[0].report_date,
            actual_end=periods[-1].report_date,
            data_as_of=periods[-1].report_date,
            periods=periods,
            period_count=len(periods),
            formula_version=FORMULA_VERSION,
            snapshot_id=snapshot_id,
            point_in_time_eligible=False,
            data_limitations=[
                "source_announcement_date is source-reported and may represent a later update; "
                "do not use this dataset for point-in-time backtesting"
            ],
        )
        locator = (
            f"iceberg://{METRICS_TABLE}?stock_code={arguments.stock_code}"
            f"&start={output.actual_start}&end={output.actual_end}&snapshot_id={snapshot_id}"
        )
        latest = periods[-1]
        evidence = Evidence(
            evidence_id=f"financial-{hashlib.sha256(locator.encode()).hexdigest()[:16]}",
            evidence_type="financial",
            subject=arguments.stock_code,
            statement=(
                f"{arguments.stock_code}财务数据覆盖{output.actual_start}至{output.actual_end}，"
                f"最新报告期营业收入为{latest.revenue}元、归母净利润为{latest.parent_net_profit}元。"
            ),
            data=output.model_dump(mode="json"),
            source=SourceReference(
                source_type="iceberg",
                locator=locator,
                observed_at=datetime.now(timezone.utc),
                metadata={
                    "table": METRICS_TABLE,
                    "snapshot_id": snapshot_id,
                    "formula_version": FORMULA_VERSION,
                },
            ),
        )
        return ToolResult(
            task_id=task_id,
            success=True,
            evidence=[evidence],
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    @staticmethod
    def _error(task_id: str, started: float, code: str, message: str) -> ToolResult:
        return ToolResult(
            task_id=task_id,
            success=False,
            error_code=code,
            error_message=message,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
