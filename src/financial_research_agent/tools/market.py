from __future__ import annotations

import hashlib
import time
from datetime import date, datetime, timezone
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field, model_validator

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import Evidence, SourceReference, ToolResult
from financial_research_agent.market.repository import MarketDataRepository
from financial_research_agent.market.schema import KLINE_DAILY_TABLE
from financial_research_agent.tools.base import FinancialTool, ToolDefinition

MAX_MARKET_ROWS = 1000
INDICATOR_FORMULA_VERSION = "market_indicators_v1"


class MarketQueryInput(BaseModel):
    stock_code: str = Field(pattern=r"^\d{6}$")
    start_date: date
    end_date: date
    adjust_type: Literal["qfq"] = "qfq"
    max_rows: int = Field(default=MAX_MARKET_ROWS, ge=1, le=MAX_MARKET_ROWS)

    @model_validator(mode="after")
    def validate_dates(self) -> MarketQueryInput:
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date")
        return self


class MarketBar(BaseModel):
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float
    turnover_rate: float


class MarketQueryOutput(BaseModel):
    stock_code: str
    adjust_type: Literal["qfq"]
    requested_start: date
    requested_end: date
    actual_start: date
    actual_end: date
    data_as_of: date
    row_count: int
    snapshot_id: int | None
    rows: list[MarketBar]


class IndicatorInput(BaseModel):
    stock_code: str = Field(pattern=r"^\d{6}$")
    start_date: date
    end_date: date
    adjust_type: Literal["qfq"] = "qfq"

    @model_validator(mode="after")
    def validate_dates(self) -> IndicatorInput:
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date")
        return self


class IndicatorOutput(BaseModel):
    stock_code: str
    adjust_type: Literal["qfq"]
    requested_start: date
    requested_end: date
    actual_start: date
    actual_end: date
    data_as_of: date
    observations: int
    period_return: float
    annualized_volatility: float | None
    ma5: float | None
    ma20: float | None
    max_drawdown: float
    relative_volume_20d: float | None
    period_high: float
    period_low: float
    formula_version: str = INDICATOR_FORMULA_VERSION
    snapshot_id: int | None


def _evidence_id(prefix: str, locator: str) -> str:
    return f"{prefix}-{hashlib.sha256(locator.encode()).hexdigest()[:16]}"


def _locator(stock_code: str, start: date, end: date, snapshot_id: int | None) -> str:
    return (
        f"iceberg://{KLINE_DAILY_TABLE}?stock_code={stock_code}"
        f"&start={start}&end={end}&adjust=qfq&snapshot_id={snapshot_id}"
    )


def _tool_error(task_id: str, started: float, code: str, message: str) -> ToolResult:
    return ToolResult(
        task_id=task_id,
        success=False,
        error_code=code,
        error_message=message,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


class MarketQueryTool(FinancialTool):
    definition = ToolDefinition(
        name="market_query",
        version="1.0.0",
        description="Read curated qfq daily bars for one allowed stock and date range.",
        timeout_seconds=15,
        max_rows=MAX_MARKET_ROWS,
        data_domain="market",
    )
    input_model = MarketQueryInput

    def __init__(self, settings: Settings, repository: MarketDataRepository | None = None) -> None:
        self.settings = settings
        self.repository = repository or MarketDataRepository(settings)

    async def execute(self, task_id: str, arguments: MarketQueryInput) -> ToolResult:
        started = time.perf_counter()
        if arguments.stock_code not in self.settings.stock_codes:
            return _tool_error(task_id, started, "STOCK_NOT_ALLOWED", "stock is outside the configured pool")
        table = self.repository.query_daily(
            arguments.stock_code, arguments.start_date, arguments.end_date
        )
        if table.num_rows == 0:
            return _tool_error(task_id, started, "MARKET_DATA_EMPTY", "no daily bars in requested range")
        if table.num_rows > arguments.max_rows:
            return _tool_error(
                task_id,
                started,
                "MARKET_ROW_LIMIT",
                f"query returned {table.num_rows} rows; maximum is {arguments.max_rows}",
            )
        frame = table.to_pandas().sort_values("trade_date")
        snapshot_id = self.repository.current_snapshot_id()
        output = MarketQueryOutput(
            stock_code=arguments.stock_code,
            adjust_type="qfq",
            requested_start=arguments.start_date,
            requested_end=arguments.end_date,
            actual_start=frame.iloc[0]["trade_date"],
            actual_end=frame.iloc[-1]["trade_date"],
            data_as_of=frame.iloc[-1]["trade_date"],
            row_count=len(frame),
            snapshot_id=snapshot_id,
            rows=[MarketBar.model_validate(row) for row in frame.to_dict("records")],
        )
        locator = _locator(
            arguments.stock_code, output.actual_start, output.actual_end, snapshot_id
        )
        evidence = Evidence(
            evidence_id=_evidence_id("market", locator),
            evidence_type="market",
            subject=arguments.stock_code,
            statement=(
                f"{arguments.stock_code}前复权日线覆盖{output.actual_start}至"
                f"{output.actual_end}，共{output.row_count}个交易日。"
            ),
            data=output.model_dump(mode="json"),
            source=SourceReference(
                source_type="iceberg",
                locator=locator,
                observed_at=datetime.now(timezone.utc),
                metadata={"table": KLINE_DAILY_TABLE, "snapshot_id": snapshot_id},
            ),
        )
        return ToolResult(
            task_id=task_id,
            success=True,
            evidence=[evidence],
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


class IndicatorTool(FinancialTool):
    definition = ToolDefinition(
        name="indicator_calculator",
        version="1.0.0",
        description="Calculate deterministic indicators from curated qfq daily bars.",
        timeout_seconds=15,
        max_rows=MAX_MARKET_ROWS,
        data_domain="market",
    )
    input_model = IndicatorInput

    def __init__(self, settings: Settings, repository: MarketDataRepository | None = None) -> None:
        self.settings = settings
        self.repository = repository or MarketDataRepository(settings)

    async def execute(self, task_id: str, arguments: IndicatorInput) -> ToolResult:
        started = time.perf_counter()
        if arguments.stock_code not in self.settings.stock_codes:
            return _tool_error(task_id, started, "STOCK_NOT_ALLOWED", "stock is outside the configured pool")
        table = self.repository.query_daily(
            arguments.stock_code, arguments.start_date, arguments.end_date
        )
        if table.num_rows == 0:
            return _tool_error(task_id, started, "MARKET_DATA_EMPTY", "no daily bars in requested range")
        if table.num_rows > MAX_MARKET_ROWS:
            return _tool_error(task_id, started, "MARKET_ROW_LIMIT", "indicator input exceeds 1000 rows")
        frame = table.to_pandas().sort_values("trade_date").reset_index(drop=True)
        output = calculate_indicators(frame, arguments, self.repository.current_snapshot_id())
        input_locator = _locator(
            arguments.stock_code, output.actual_start, output.actual_end, output.snapshot_id
        )
        locator = f"calculation://{INDICATOR_FORMULA_VERSION}?input={input_locator}"
        evidence = Evidence(
            evidence_id=_evidence_id("indicator", locator),
            evidence_type="indicator",
            subject=arguments.stock_code,
            statement=(
                f"{arguments.stock_code}在{output.actual_start}至{output.actual_end}的"
                f"区间收益率为{output.period_return:.4%}，最大回撤为{output.max_drawdown:.4%}。"
            ),
            data=output.model_dump(mode="json"),
            source=SourceReference(
                source_type="calculation",
                locator=locator,
                observed_at=datetime.now(timezone.utc),
                metadata={
                    "formula_version": INDICATOR_FORMULA_VERSION,
                    "input_locator": input_locator,
                    "snapshot_id": output.snapshot_id,
                },
            ),
        )
        return ToolResult(
            task_id=task_id,
            success=True,
            evidence=[evidence],
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


def calculate_indicators(
    frame: pd.DataFrame, arguments: IndicatorInput, snapshot_id: int | None
) -> IndicatorOutput:
    close = frame["close"].astype(float)
    volume = frame["volume"].astype(float)
    daily_returns = close.pct_change().dropna()
    drawdowns = close / close.cummax() - 1.0
    return IndicatorOutput(
        stock_code=arguments.stock_code,
        adjust_type="qfq",
        requested_start=arguments.start_date,
        requested_end=arguments.end_date,
        actual_start=frame.iloc[0]["trade_date"],
        actual_end=frame.iloc[-1]["trade_date"],
        data_as_of=frame.iloc[-1]["trade_date"],
        observations=len(frame),
        period_return=float(close.iloc[-1] / close.iloc[0] - 1.0),
        annualized_volatility=(
            float(daily_returns.std(ddof=1) * (252**0.5)) if len(daily_returns) >= 2 else None
        ),
        ma5=float(close.tail(5).mean()) if len(close) >= 5 else None,
        ma20=float(close.tail(20).mean()) if len(close) >= 20 else None,
        max_drawdown=float(drawdowns.min()),
        relative_volume_20d=(
            float(volume.iloc[-1] / volume.tail(20).mean())
            if len(volume) >= 20 and volume.tail(20).mean() > 0
            else None
        ),
        period_high=float(frame["high"].max()),
        period_low=float(frame["low"].min()),
        formula_version=INDICATOR_FORMULA_VERSION,
        snapshot_id=snapshot_id,
    )
