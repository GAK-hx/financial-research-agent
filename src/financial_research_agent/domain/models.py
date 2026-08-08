from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Intent(StrEnum):
    MARKET = "market"
    TECHNICAL = "technical"
    FINANCIAL = "financial"
    FUNDAMENTAL = "fundamental"
    REPORT = "report"
    EVENT = "event"
    SCREENING = "screening"
    FACTOR = "factor"
    COMPREHENSIVE = "comprehensive"


class ToolName(StrEnum):
    MARKET_QUERY = "market_query"
    INDICATOR_CALCULATOR = "indicator_calculator"
    FINANCIAL_QUERY = "financial_query"
    STOCK_COMPARISON = "stock_comparison"
    REPORT_SEARCH = "report_search"
    TECHNICAL_ANALYSIS = "technical_analysis"
    FUNDAMENTAL_ANALYSIS = "fundamental_analysis"
    FACTOR_SCREEN = "factor_screen"
    EVENT_SEARCH = "event_search"


class ResearchRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    tenant_id: str = Field(
        default="local",
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$",
    )
    user_id: str = Field(
        default="local",
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$",
    )
    session_id: str = Field(
        default="default",
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$",
    )


class ResolvedTimeExpression(BaseModel):
    original_text: str = Field(default="", max_length=200)
    kind: Literal[
        "absolute_range",
        "relative_rolling",
        "complete_period",
        "calendar_period",
        "latest_available",
        "default_window",
        "not_applicable",
    ]
    granularity: Literal["day", "month", "quarter", "year", "unspecified"]
    quantity: int | None = Field(default=None, ge=1, le=120)
    start_date: date | None = None
    end_date: date | None = None
    complete_period: bool = False
    calendar: Literal["calendar", "trading", "not_applicable"] = "calendar"
    resolution_rule: str = "time_scope_v1"

    @model_validator(mode="after")
    def validate_range(self) -> ResolvedTimeExpression:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("resolved time expression has an invalid date range")
        if self.complete_period and self.kind not in {
            "complete_period",
            "calendar_period",
        }:
            raise ValueError("only period expressions may be marked complete")
        return self


class QuerySpec(BaseModel):
    stock_codes: list[str] = Field(min_length=1, max_length=20)
    start_date: date | None = None
    end_date: date | None = None
    intent: Intent
    dimensions: list[str] = Field(default_factory=list, max_length=8)
    analysis_domains: list[
        Literal["market", "financial", "report", "event", "factor"]
    ] = Field(
        default_factory=list,
        max_length=5,
    )
    time_scope: ResolvedTimeExpression | None = None

    @model_validator(mode="after")
    def validate_dates_and_codes(self) -> QuerySpec:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date")
        if any(len(code) != 6 or not code.isdigit() for code in self.stock_codes):
            raise ValueError("stock code must contain exactly six digits")
        if len(self.analysis_domains) != len(set(self.analysis_domains)):
            raise ValueError("analysis_domains must be unique")
        return self


class SemanticAlignmentResult(BaseModel):
    passed: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    extracted_stock_codes: list[str] = Field(default_factory=list)
    expected_intent: Intent | None = None
    expected_dimensions: list[str] = Field(default_factory=list)
    expected_analysis_domains: list[str] = Field(default_factory=list)
    resolved_time_expression: ResolvedTimeExpression | None = None


class ExecutionMetadata(BaseModel):
    executed_at: datetime
    business_reference_date: date
    timezone: str
    data_as_of: date | None = None


class AnalysisTask(BaseModel):
    task_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    tool_name: ToolName
    arguments: dict[str, Any]
    depends_on: list[str] = Field(default_factory=list, max_length=6)


class AnalysisPlan(BaseModel):
    query: QuerySpec
    tasks: list[AnalysisTask] = Field(min_length=1, max_length=12)
    expected_sections: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def validate_task_graph(self) -> AnalysisPlan:
        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("task_id must be unique")
        known = set(task_ids)
        for task in self.tasks:
            if task.task_id in task.depends_on:
                raise ValueError("task cannot depend on itself")
            if not set(task.depends_on).issubset(known):
                raise ValueError("task depends on an unknown task")
        return self


class SourceReference(BaseModel):
    source_type: Literal["iceberg", "milvus", "calculation", "knowledge"]
    locator: str
    observed_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class Evidence(BaseModel):
    evidence_id: str
    evidence_type: Literal[
        "market",
        "financial",
        "indicator",
        "research_report",
        "technical",
        "fundamental",
        "factor",
        "event",
        "comparison",
    ]
    subject: str
    statement: str
    data: dict[str, Any] = Field(default_factory=dict)
    source: SourceReference


class ToolResult(BaseModel):
    task_id: str
    success: bool
    evidence: list[Evidence] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    latency_ms: int = Field(ge=0)


class ReportClaim(BaseModel):
    claim: str = Field(min_length=2, max_length=2000)
    evidence_ids: list[str] = Field(min_length=1)
    confidence: Literal["high", "medium", "low"]


class ReportRisk(BaseModel):
    risk: str = Field(min_length=2, max_length=2000)
    classification: Literal["fact", "calculation", "model_interpretation"]
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    confidence: Literal["high", "medium", "low"] = "medium"


class ReportLimitation(BaseModel):
    limitation: str = Field(min_length=2, max_length=2000)
    category: Literal["data", "scope", "method"] = "scope"
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class ReportRiskDimension(BaseModel):
    dimension: Literal["technical", "fundamental", "event", "data_confidence"]
    level: Literal["low", "medium", "high", "unknown"]
    rationale: str = Field(min_length=2, max_length=1000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class ReportScenario(BaseModel):
    name: Literal["optimistic", "base", "stress"]
    assumptions: list[str] = Field(min_length=1, max_length=8)
    implication: str = Field(min_length=2, max_length=1500)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class ResearchReport(BaseModel):
    subjects: list[str] = Field(min_length=1, max_length=20)
    summary: str = Field(min_length=2, max_length=4000)
    summary_evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    claims: list[ReportClaim] = Field(min_length=1, max_length=30)
    risks: list[ReportRisk] = Field(min_length=1, max_length=20)
    limitations: list[ReportLimitation] = Field(default_factory=list, max_length=20)
    risk_vector: list[ReportRiskDimension] = Field(default_factory=list, max_length=4)
    scenarios: list[ReportScenario] = Field(default_factory=list, max_length=3)
    data_as_of: date | None = None
    disclaimer: str = "仅供研究参考，不构成投资建议。"

    @field_validator("risks", mode="before")
    @classmethod
    def migrate_legacy_risks(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [
                {
                    "risk": item,
                    "classification": "model_interpretation",
                    "evidence_ids": [],
                    "confidence": "low",
                }
                if isinstance(item, str)
                else item
                for item in value
            ]
        return value

    @field_validator("limitations", mode="before")
    @classmethod
    def migrate_legacy_limitations(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [
                {"limitation": item, "category": "scope", "evidence_ids": []}
                if isinstance(item, str)
                else item
                for item in value
            ]
        return value


class ValidationResult(BaseModel):
    passed: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
