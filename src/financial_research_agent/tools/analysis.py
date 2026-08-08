from __future__ import annotations

import hashlib
import json
import time
from datetime import date, datetime, timezone

from pydantic import BaseModel, Field, model_validator

from financial_research_agent.analysis.engine import (
    FUNDAMENTAL_FORMULA_VERSION,
    TECHNICAL_FORMULA_VERSION,
    calculate_fundamental_snapshot,
    calculate_technical_snapshot,
)
from financial_research_agent.analysis.registry import FactorRegistry, UniverseRegistry
from financial_research_agent.analysis.repository import AnalysisRepository
from financial_research_agent.analysis.schema import FACTOR_VALUES_TABLE
from financial_research_agent.config import Settings
from financial_research_agent.domain.models import Evidence, SourceReference, ToolResult
from financial_research_agent.financial.repository import FinancialDataRepository
from financial_research_agent.financial.schema import METRICS_TABLE
from financial_research_agent.market.repository import MarketDataRepository
from financial_research_agent.market.schema import KLINE_DAILY_TABLE
from financial_research_agent.tools.base import FinancialTool, ToolDefinition


def _error(task_id: str, started: float, code: str, message: str) -> ToolResult:
    return ToolResult(
        task_id=task_id,
        success=False,
        error_code=code,
        error_message=message,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def _evidence_id(prefix: str, locator: str) -> str:
    return f"{prefix}-{hashlib.sha256(locator.encode()).hexdigest()[:16]}"


class TechnicalAnalysisInput(BaseModel):
    stock_code: str = Field(pattern=r"^\d{6}$")
    start_date: date
    end_date: date
    adjust_type: str = Field(default="qfq", pattern=r"^qfq$")

    @model_validator(mode="after")
    def validate_dates(self) -> TechnicalAnalysisInput:
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date")
        return self


class TechnicalAnalysisTool(FinancialTool):
    definition = ToolDefinition(
        name="technical_analysis",
        version="1.0.0",
        description=(
            "Calculate reproducible qfq trend, momentum, volatility, drawdown, volume and "
            "Amihud liquidity metrics for one stock. Requires curated daily bars; it does not "
            "predict prices or issue trading signals. Returns technical Evidence."
        ),
        timeout_seconds=20,
        max_rows=1000,
        data_domain="market",
    )
    input_model = TechnicalAnalysisInput

    def __init__(self, settings: Settings, repository: MarketDataRepository | None = None) -> None:
        self.settings = settings
        self.repository = repository or MarketDataRepository(settings)

    async def execute(self, task_id: str, arguments: TechnicalAnalysisInput) -> ToolResult:
        started = time.perf_counter()
        if arguments.stock_code not in self.settings.allowed_stock_codes:
            return _error(task_id, started, "STOCK_NOT_ALLOWED", "stock is outside analysis universe")
        table = self.repository.query_daily(arguments.stock_code, arguments.start_date, arguments.end_date)
        if table.num_rows == 0:
            return _error(task_id, started, "MARKET_DATA_EMPTY", "no daily bars in requested range")
        if table.num_rows > 1000:
            return _error(task_id, started, "MARKET_ROW_LIMIT", "technical input exceeds 1000 rows")
        snapshot = calculate_technical_snapshot(arguments.stock_code, table.to_pandas())
        input_snapshot = self.repository.current_snapshot_id()
        input_locator = (
            f"iceberg://{KLINE_DAILY_TABLE}?stock_code={arguments.stock_code}"
            f"&start={arguments.start_date}&end={arguments.end_date}"
            f"&adjust=qfq&snapshot_id={input_snapshot}"
        )
        locator = f"calculation://{TECHNICAL_FORMULA_VERSION}?input={input_locator}"
        evidence = Evidence(
            evidence_id=_evidence_id("technical", locator),
            evidence_type="technical",
            subject=arguments.stock_code,
            statement=(
                f"{arguments.stock_code}技术分析截至{snapshot.as_of_date}，"
                f"趋势状态为{snapshot.trend_state}，20日动量为{snapshot.momentum_20d}，"
                f"20日年化波动率为{snapshot.volatility_20d}。"
            ),
            data=snapshot.model_dump(mode="json"),
            source=SourceReference(
                source_type="calculation",
                locator=locator,
                observed_at=datetime.now(timezone.utc),
                metadata={
                    "formula_version": TECHNICAL_FORMULA_VERSION,
                    "input_locator": input_locator,
                    "snapshot_id": input_snapshot,
                    "adjust_type": "qfq",
                },
            ),
        )
        return ToolResult(
            task_id=task_id,
            success=True,
            evidence=[evidence],
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


class FundamentalAnalysisInput(BaseModel):
    stock_code: str = Field(pattern=r"^\d{6}$")
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_dates(self) -> FundamentalAnalysisInput:
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date")
        return self


class FundamentalAnalysisTool(FinancialTool):
    definition = ToolDefinition(
        name="fundamental_analysis",
        version="1.0.0",
        description=(
            "Calculate a latest-snapshot fundamental vector covering growth, ROE, cash-flow "
            "quality and leverage. The current financial source is not point-in-time eligible "
            "and must not be used for historical backtests. Returns fundamental Evidence."
        ),
        timeout_seconds=20,
        max_rows=40,
        data_domain="financial",
    )
    input_model = FundamentalAnalysisInput

    def __init__(self, settings: Settings, repository: FinancialDataRepository | None = None) -> None:
        self.settings = settings
        self.repository = repository or FinancialDataRepository(settings)

    async def execute(self, task_id: str, arguments: FundamentalAnalysisInput) -> ToolResult:
        started = time.perf_counter()
        if arguments.stock_code not in self.settings.allowed_stock_codes:
            return _error(task_id, started, "STOCK_NOT_ALLOWED", "stock is outside analysis universe")
        table = self.repository.query_metrics(arguments.stock_code, arguments.start_date, arguments.end_date)
        if table.num_rows == 0:
            return _error(task_id, started, "FINANCIAL_DATA_EMPTY", "no financial periods found")
        snapshot = calculate_fundamental_snapshot(arguments.stock_code, table.to_pandas())
        input_snapshot = self.repository.current_snapshot_id()
        input_locator = (
            f"iceberg://{METRICS_TABLE}?stock_code={arguments.stock_code}"
            f"&start={arguments.start_date}&end={arguments.end_date}&snapshot_id={input_snapshot}"
        )
        locator = f"calculation://{FUNDAMENTAL_FORMULA_VERSION}?input={input_locator}"
        evidence = Evidence(
            evidence_id=_evidence_id("fundamental", locator),
            evidence_type="fundamental",
            subject=arguments.stock_code,
            statement=(
                f"{arguments.stock_code}基本面快照报告期为{snapshot.report_date}，"
                f"营收同比为{snapshot.revenue_growth}，归母净利润同比为{snapshot.profit_growth}，"
                "该结果不具备历史时点回测资格。"
            ),
            data=snapshot.model_dump(mode="json"),
            source=SourceReference(
                source_type="calculation",
                locator=locator,
                observed_at=datetime.now(timezone.utc),
                metadata={
                    "formula_version": FUNDAMENTAL_FORMULA_VERSION,
                    "input_locator": input_locator,
                    "snapshot_id": input_snapshot,
                    "point_in_time_eligible": False,
                },
            ),
        )
        return ToolResult(
            task_id=task_id,
            success=True,
            evidence=[evidence],
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


class FactorScreenInput(BaseModel):
    stock_codes: list[str] = Field(min_length=1, max_length=20)
    as_of_date: date
    universe_id: str = Field(default="demo_liquid_a_share", pattern=r"^[a-z][a-z0-9_]{2,63}$")
    factor_names: list[str] = Field(min_length=1, max_length=12)
    top_n: int = Field(default=10, ge=1, le=20)

    @model_validator(mode="after")
    def validate_codes(self) -> FactorScreenInput:
        if any(len(code) != 6 or not code.isdigit() for code in self.stock_codes):
            raise ValueError("stock code must contain exactly six digits")
        return self


class FactorScreenTool(FinancialTool):
    definition = ToolDefinition(
        name="factor_screen",
        version="1.0.0",
        description=(
            "Read versioned Spark factor results from Iceberg and return coverage-aware rankings. "
            "It never computes factors inside the model and never hides missing universe members. "
            "Fundamental factors are current-snapshot only, not point-in-time backtest evidence."
        ),
        timeout_seconds=20,
        max_rows=240,
        data_domain="financial",
    )
    input_model = FactorScreenInput

    def __init__(self, settings: Settings, repository: AnalysisRepository | None = None) -> None:
        self.settings = settings
        self.repository = repository or AnalysisRepository(settings)
        self.factors = FactorRegistry.builtin()
        self.universes = UniverseRegistry.builtin()

    async def execute(self, task_id: str, arguments: FactorScreenInput) -> ToolResult:
        started = time.perf_counter()
        try:
            universe = self.universes.get(arguments.universe_id)
            for name in arguments.factor_names:
                self.factors.get(name)
        except ValueError as exc:
            return _error(task_id, started, "FACTOR_ARGUMENT_INVALID", str(exc))
        if not set(arguments.stock_codes).issubset(universe.members):
            return _error(task_id, started, "STOCK_NOT_IN_UNIVERSE", "query contains stock outside universe")
        table = self.repository.query_factor_values(
            universe_id=arguments.universe_id,
            as_of_date=arguments.as_of_date,
            factor_names=arguments.factor_names,
        )
        if table.num_rows == 0:
            return _error(task_id, started, "FACTOR_DATA_EMPTY", "run the factor-batch Docker profile first")
        frame = table.to_pandas()
        frame = frame[frame["stock_code"].isin(arguments.stock_codes)]
        valid = frame[frame["status"] == "valid"].sort_values(
            ["factor_name", "percentile_rank"], ascending=[True, False]
        )
        missing = frame[frame["status"] != "valid"]
        run_id = str(frame.iloc[0]["run_id"])
        as_of = frame.iloc[0]["as_of_date"]
        payload = {
            "universe_id": universe.universe_id,
            "universe_version": universe.version,
            "selection_policy": universe.selection_policy,
            "as_of_date": as_of,
            "requested_stocks": arguments.stock_codes,
            "requested_factors": arguments.factor_names,
            "rankings": json.loads(
                valid.head(arguments.top_n * len(arguments.factor_names)).to_json(
                    orient="records", date_format="iso"
                )
            ),
            "missing": json.loads(
                missing[["stock_code", "factor_name", "missing_reason"]].to_json(
                    orient="records", date_format="iso"
                )
            ),
            "actual_covered_stocks": sorted(valid["stock_code"].unique().tolist()),
            "registry_version": self.factors.version,
            "run_id": run_id,
            "point_in_time_warning": (
                "fundamental factors in this run are current-snapshot only and are not eligible "
                "for historical point-in-time backtests"
            ),
        }
        locator = (
            f"iceberg://{FACTOR_VALUES_TABLE}?run_id={run_id}&universe={universe.universe_id}"
            f"&as_of={as_of}&factors={','.join(arguments.factor_names)}"
        )
        evidence = Evidence(
            evidence_id=_evidence_id("factor", locator),
            evidence_type="factor",
            subject=arguments.stock_codes[0],
            statement=(
                f"{universe.universe_id}@{universe.version}因子结果截至{as_of}；"
                f"请求{len(arguments.stock_codes)}只股票，实际有有效因子数据"
                f"{len(payload['actual_covered_stocks'])}只，缺失记录{len(payload['missing'])}条。"
            ),
            data=payload,
            source=SourceReference(
                source_type="iceberg",
                locator=locator,
                observed_at=datetime.now(timezone.utc),
                metadata={
                    "table": FACTOR_VALUES_TABLE,
                    "registry_version": self.factors.version,
                    "universe_version": universe.version,
                    "run_id": run_id,
                },
            ),
        )
        return ToolResult(
            task_id=task_id,
            success=True,
            evidence=[evidence],
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


class StockComparisonInput(BaseModel):
    stock_codes: list[str] = Field(min_length=2, max_length=5)
    start_date: date
    end_date: date


class StockComparisonTool(FinancialTool):
    definition = ToolDefinition(
        name="stock_comparison",
        version="1.0.0",
        description=(
            "Compare 2-5 stocks using deterministic technical risk vectors from the same date "
            "range. It does not forecast price direction or execute trades."
        ),
        timeout_seconds=30,
        max_rows=5,
        data_domain="market",
    )
    input_model = StockComparisonInput

    def __init__(self, settings: Settings, repository: MarketDataRepository | None = None) -> None:
        self.settings = settings
        self.repository = repository or MarketDataRepository(settings)

    async def execute(self, task_id: str, arguments: StockComparisonInput) -> ToolResult:
        started = time.perf_counter()
        outputs = []
        locators = []
        for stock_code in arguments.stock_codes:
            if stock_code not in self.settings.allowed_stock_codes:
                return _error(task_id, started, "STOCK_NOT_ALLOWED", f"{stock_code} outside universe")
            table = self.repository.query_daily(stock_code, arguments.start_date, arguments.end_date)
            if table.num_rows == 0:
                continue
            outputs.append(calculate_technical_snapshot(stock_code, table.to_pandas()).model_dump(mode="json"))
            locators.append(
                f"iceberg://{KLINE_DAILY_TABLE}?stock_code={stock_code}&start={arguments.start_date}"
                f"&end={arguments.end_date}&snapshot_id={self.repository.current_snapshot_id()}"
            )
        if len(outputs) < 2:
            return _error(task_id, started, "COMPARISON_COVERAGE_INSUFFICIENT", "fewer than two stocks have data")
        input_locator = "|".join(locators)
        locator = f"calculation://stock_comparison_v1?inputs={hashlib.sha256(input_locator.encode()).hexdigest()}"
        evidence = Evidence(
            evidence_id=_evidence_id("comparison", locator),
            evidence_type="comparison",
            subject=outputs[0]["stock_code"],
            statement=f"同口径比较覆盖{len(outputs)}只股票，未覆盖股票被明确排除。",
            data={"rows": outputs, "coverage_count": len(outputs), "requested": arguments.stock_codes},
            source=SourceReference(
                source_type="calculation",
                locator=locator,
                observed_at=datetime.now(timezone.utc),
                metadata={"formula_version": "stock_comparison_v1", "input_locator": input_locator},
            ),
        )
        return ToolResult(task_id=task_id, success=True, evidence=[evidence], latency_ms=int((time.perf_counter() - started) * 1000))
