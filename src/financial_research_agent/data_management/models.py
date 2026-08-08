from __future__ import annotations

from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class DataTier(StrEnum):
    RAW = "raw"
    STANDARDIZED = "standardized"
    CURATED = "curated"
    DERIVED = "derived"
    SIMULATION = "simulation"


class BatchStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    WARNING = "warning"
    FAILED = "failed"


class QualitySeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


class SourceMetadata(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    endpoint: str = Field(min_length=1, max_length=256)
    mapping_version: str = Field(min_length=1, max_length=32)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    parameters: dict[str, Any] = Field(default_factory=dict)


class QualityIssue(BaseModel):
    rule: str = Field(min_length=1, max_length=128)
    severity: QualitySeverity
    message: str = Field(min_length=1, max_length=1000)
    row_number: int | None = Field(default=None, ge=0)
    field: str | None = None
    value: Any | None = None


class DataQualityResult(BaseModel):
    checked_rows: int = Field(ge=0)
    accepted_rows: int = Field(ge=0)
    rejected_rows: int = Field(ge=0)
    issues: list[QualityIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_counts(self) -> DataQualityResult:
        if self.accepted_rows + self.rejected_rows != self.checked_rows:
            raise ValueError("accepted_rows + rejected_rows must equal checked_rows")
        return self

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == QualitySeverity.ERROR for issue in self.issues)


class IngestionBatch(BaseModel):
    batch_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,96}$")
    dataset: str = Field(min_length=1, max_length=128)
    tier: DataTier
    source: SourceMetadata
    requested_start: date | None = None
    requested_end: date | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    input_rows: int = Field(default=0, ge=0)
    output_rows: int = Field(default=0, ge=0)
    rejected_rows: int = Field(default=0, ge=0)
    target_table: str | None = None
    snapshot_id: int | None = None
    config_version: str = "v1"
    code_version: str = "unknown"
    status: BatchStatus = BatchStatus.RUNNING
    message: str | None = None

    @model_validator(mode="after")
    def validate_batch(self) -> IngestionBatch:
        if self.requested_start and self.requested_end and self.requested_end < self.requested_start:
            raise ValueError("requested_end cannot be earlier than requested_start")
        if self.output_rows + self.rejected_rows > self.input_rows:
            raise ValueError("output_rows + rejected_rows cannot exceed input_rows")
        if self.status != BatchStatus.RUNNING and self.finished_at is None:
            raise ValueError("a finished batch requires finished_at")
        return self
