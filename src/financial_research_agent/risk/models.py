from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class RiskCategory(StrEnum):
    LIQUIDITY = "liquidity"
    EARNINGS_QUALITY = "earnings_quality"
    ASSET_QUALITY = "asset_quality"
    DISCLOSURE_AUDIT = "disclosure_audit"


class RiskStatus(StrEnum):
    CLEAR = "clear"
    WATCH = "watch"
    ESCALATE = "escalate"
    INSUFFICIENT_DATA = "insufficient_data"
    AMBIGUOUS = "ambiguous"


class DataAvailability(StrEnum):
    PRESENT = "present"
    NOT_DISCLOSED = "not_disclosed"
    NOT_AVAILABLE_FROM_SOURCE = "not_available_from_source"
    REJECTED_BY_QUALITY = "rejected_by_quality"


class MissingPolicy(StrEnum):
    INSUFFICIENT = "insufficient"
    SKIP_INDICATOR = "skip_indicator"
    EXPLICIT_FALSE_ONLY = "explicit_false_only"


class BenchmarkSplit(StrEnum):
    DEVELOPMENT = "development"
    PRIVATE_HOLDOUT = "private_holdout"


class DisclosureEventType(StrEnum):
    ANNUAL_REPORT = "annual_report"
    FINANCIAL_RESTATEMENT = "financial_restatement"
    REGULATORY_INQUIRY = "regulatory_inquiry"
    AUDIT_REPORT = "audit_report"
    DEBT_OR_LIQUIDITY_ALERT = "debt_or_liquidity_alert"
    IMPAIRMENT = "impairment"
    EARNINGS_FORECAST_REVISION = "earnings_forecast_revision"
    OTHER = "other"


class DisclosureEvent(BaseModel):
    event_id: str = Field(pattern=r"^disclosure-[a-f0-9]{24}$")
    issuer_id: str = Field(pattern=r"^[0-9]{6}$")
    issuer_name: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=500)
    published_at: datetime
    url: str = Field(min_length=8, max_length=2000)
    source_name: str = Field(min_length=1, max_length=64)
    source_record_id: str = Field(min_length=1, max_length=2000)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    query_tags: list[str] = Field(min_length=1)
    event_types: list[DisclosureEventType] = Field(min_length=1)
    requires_document_review: bool = True
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_timestamps(self) -> DisclosureEvent:
        if self.published_at.tzinfo is None or self.observed_at.tzinfo is None:
            raise ValueError("published_at and observed_at must be timezone-aware")
        if self.published_at > self.observed_at:
            raise ValueError("disclosure cannot be observed before publication")
        return self


class IssuerPoolEntry(BaseModel):
    issuer_id: str = Field(pattern=r"^[0-9]{6}$")
    issuer_name: str = Field(min_length=2, max_length=64)
    industry_group: str = Field(min_length=2, max_length=64)
    business_type: Literal["non_financial", "bank", "insurance", "securities", "real_estate"]
    generic_ratio_applicable: bool
    selection_reason: str = Field(min_length=2, max_length=500)


class IssuerPool(BaseModel):
    pool_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    version: str = Field(pattern=r"^v[0-9]+$")
    frozen_at: date
    selection_policy: str = Field(min_length=10, max_length=2000)
    entries: list[IssuerPoolEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_entries(self) -> IssuerPool:
        identifiers = [item.issuer_id for item in self.entries]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("issuer pool cannot contain duplicate issuer_id values")
        return self


class EvidencePointer(BaseModel):
    evidence_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    source_name: str = Field(min_length=1, max_length=64)
    source_record_id: str = Field(min_length=1, max_length=256)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    published_at: datetime
    locator: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def require_timezone(self) -> EvidencePointer:
        if self.published_at.tzinfo is None:
            raise ValueError("published_at must be timezone-aware")
        return self


class RiskFact(BaseModel):
    issuer_id: str = Field(pattern=r"^[0-9]{6}$")
    report_period: date
    metric_code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    value: float | None = None
    unit: str = Field(min_length=1, max_length=32)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    availability: DataAvailability
    source_name: str = Field(min_length=1, max_length=64)
    source_record_id: str = Field(min_length=1, max_length=256)
    source_published_at: datetime
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    revision_no: int = Field(default=0, ge=0)
    snapshot_id: int | None = Field(default=None, gt=0)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_fact(self) -> RiskFact:
        if self.source_published_at.tzinfo is None or self.observed_at.tzinfo is None:
            raise ValueError("source_published_at and observed_at must be timezone-aware")
        if self.source_published_at > self.observed_at:
            raise ValueError("source cannot be observed before it is published")
        if self.report_period > self.source_published_at.date():
            raise ValueError("report_period cannot be later than source_published_at")
        if self.availability == DataAvailability.PRESENT and self.value is None:
            raise ValueError("present fact requires a numeric value")
        if self.availability != DataAvailability.PRESENT and self.value is not None:
            raise ValueError("unavailable fact cannot carry a numeric value")
        return self


class PointInTimeBoundary(BaseModel):
    as_of_date: date
    system_cutoff: datetime
    data_snapshot_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

    @model_validator(mode="after")
    def require_timezone(self) -> PointInTimeBoundary:
        if self.system_cutoff.tzinfo is None:
            raise ValueError("system_cutoff must be timezone-aware")
        return self


class RiskThreshold(BaseModel):
    status: Literal["watch", "escalate"]
    operator: Literal["lt", "le", "gt", "ge", "eq"]
    value: float


class RiskMetricDefinition(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    version: str = Field(pattern=r"^v[0-9]+(?:\.[0-9]+){0,2}$")
    name_zh: str = Field(min_length=2, max_length=64)
    category: RiskCategory
    formula: str = Field(min_length=1, max_length=512)
    input_metrics: list[str] = Field(min_length=1)
    unit: str = Field(min_length=1, max_length=32)
    direction: Literal["higher_is_riskier", "lower_is_riskier", "boolean_flag"]
    missing_policy: MissingPolicy
    minimum_periods: int = Field(default=1, ge=1, le=12)
    thresholds: list[RiskThreshold] = Field(min_length=1, max_length=2)
    minimum_evidence_types: list[str] = Field(min_length=1)
    notes: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_thresholds(self) -> RiskMetricDefinition:
        states = [threshold.status for threshold in self.thresholds]
        if len(states) != len(set(states)):
            raise ValueError("threshold status must be unique per metric")
        if self.direction == "boolean_flag" and any(
            threshold.operator != "eq" for threshold in self.thresholds
        ):
            raise ValueError("boolean_flag metrics require equality thresholds")
        return self


class RiskLabel(BaseModel):
    status: RiskStatus
    categories: list[RiskCategory] = Field(default_factory=list)
    outcome_date: date | None = None
    outcome_type: str | None = Field(default=None, max_length=128)
    evidence_ids: list[str] = Field(default_factory=list)
    annotator_id: str | None = Field(default=None, max_length=64)
    rationale: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_label(self) -> RiskLabel:
        if self.status == RiskStatus.ESCALATE and not self.evidence_ids:
            raise ValueError("escalate label requires evidence")
        if self.status == RiskStatus.AMBIGUOUS and not self.rationale:
            raise ValueError("ambiguous label requires rationale")
        return self


class BenchmarkExpectedAnswer(BaseModel):
    answer_type: Literal[
        "fact",
        "calculation",
        "risk_candidate",
        "evidence",
        "counterevidence",
        "agent_team",
        "missing_data",
    ]
    payload: dict[str, Any]
    evidence_ids: list[str] = Field(default_factory=list)
    numeric_tolerance: float | None = Field(default=None, ge=0)


class IssuerRiskCase(BaseModel):
    case_id: str = Field(pattern=r"^irb-[0-9]{4}$")
    dataset_version: str = Field(pattern=r"^issuer-risk-bench-v[0-9]+$")
    split: BenchmarkSplit
    issuer_id: str = Field(pattern=r"^[0-9]{6}$")
    report_period: date
    boundary: PointInTimeBoundary
    task_type: Literal[
        "retrieval",
        "calculation",
        "risk_detection",
        "evidence_validation",
        "counterevidence",
        "team_selection",
        "missing_or_conflict",
    ]
    question: str = Field(min_length=1, max_length=2000)
    gold_label: RiskLabel | None = None
    expected_answer: BenchmarkExpectedAnswer | None = None
    annotation_status: Literal[
        "deterministic_verified",
        "pending_human_review",
        "adjudicated",
        "design_reference",
    ] = "pending_human_review"
    evidence: list[EvidencePointer] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_temporal_boundary(self) -> IssuerRiskCase:
        if self.report_period > self.boundary.as_of_date:
            raise ValueError("report_period cannot be later than as_of_date")
        visible_ids = {
            item.evidence_id
            for item in self.evidence
            if item.published_at.date() <= self.boundary.as_of_date
        }
        if self.expected_answer is not None and not set(
            self.expected_answer.evidence_ids
        ).issubset(visible_ids):
            raise ValueError("expected-answer evidence must be visible by as_of_date")
        if self.gold_label is not None and not set(self.gold_label.evidence_ids).issubset(
            visible_ids
        ):
            raise ValueError("gold evidence must be visible by as_of_date")
        if (
            self.gold_label is not None
            and self.gold_label.outcome_date is not None
            and self.gold_label.outcome_date <= self.boundary.as_of_date
        ):
            raise ValueError("outcome_date must be later than as_of_date")
        return self
