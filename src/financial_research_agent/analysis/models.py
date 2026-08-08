from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class FactorDirection(StrEnum):
    HIGHER = "higher_is_better"
    LOWER = "lower_is_better"
    NEUTRAL = "neutral"


class FactorDomain(StrEnum):
    MARKET = "market"
    FUNDAMENTAL = "fundamental"


class FactorDefinition(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    domain: FactorDomain
    description: str = Field(min_length=5, max_length=500)
    formula: str = Field(min_length=3, max_length=1000)
    input_fields: list[str] = Field(min_length=1, max_length=12)
    window: int | None = Field(default=None, ge=1, le=1000)
    direction: FactorDirection
    null_rule: str = Field(min_length=3, max_length=500)
    adjustment: Literal["qfq", "not_applicable"]
    standardization: Literal["percentile_rank", "none"] = "percentile_rank"
    winsorization: Literal["none", "mad_3"] = "none"
    formula_version: str = Field(pattern=r"^[a-z0-9_.-]{3,64}$")
    point_in_time_eligible: bool


class FactorValue(BaseModel):
    run_id: str
    stock_code: str = Field(pattern=r"^\d{6}$")
    as_of_date: date
    available_at: datetime
    universe_id: str
    universe_version: str
    factor_name: str
    factor_value: float | None = None
    percentile_rank: float | None = Field(default=None, ge=0, le=1)
    coverage_count: int = Field(default=0, ge=0)
    registry_version: str
    formula_version: str
    input_snapshot_id: int | None = None
    status: Literal["valid", "missing"]
    missing_reason: str | None = None
    point_in_time_eligible: bool
    computed_at: datetime

    @model_validator(mode="after")
    def validate_status(self) -> FactorValue:
        if self.status == "valid" and self.factor_value is None:
            raise ValueError("valid factor requires factor_value")
        if self.status == "missing" and not self.missing_reason:
            raise ValueError("missing factor requires missing_reason")
        return self


class TechnicalSnapshot(BaseModel):
    stock_code: str
    as_of_date: date
    observations: int
    close: float
    ma5: float | None
    ma20: float | None
    momentum_20d: float | None
    momentum_60d: float | None
    reversal_5d: float | None
    volatility_20d: float | None
    max_drawdown_60d: float | None
    relative_volume_20d: float | None
    amihud_liquidity_20d: float | None
    trend_state: Literal["bullish", "bearish", "mixed", "insufficient"]
    formula_version: str


class FundamentalSnapshot(BaseModel):
    stock_code: str
    report_date: date
    available_at: date | None
    revenue_growth: float | None
    profit_growth: float | None
    roe: float | None
    operating_cashflow_to_profit: float | None
    debt_to_assets: float | None
    point_in_time_eligible: bool = False
    data_limitations: list[str] = Field(default_factory=list)
    formula_version: str


class MissingEvidence(BaseModel):
    evidence_type: str
    required: int = Field(ge=1)
    actual: int = Field(ge=0)
    reason: str
    candidate_tool: str | None = None
    safe_arguments: dict = Field(default_factory=dict)


class EvidenceSufficiency(BaseModel):
    passed: bool
    missing: list[MissingEvidence] = Field(default_factory=list)
    replan_allowed: bool = False
    no_progress: bool = False
    termination_reason: str | None = None
