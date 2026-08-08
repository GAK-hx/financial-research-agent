from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class KnowledgeEventStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class RawKnowledgeItem(BaseModel):
    source_record_id: str = Field(min_length=1, max_length=256)
    symbol: str = Field(pattern=r"^\d{6}$")
    event_type: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    title: str = Field(min_length=2, max_length=500)
    content: str = Field(min_length=20, max_length=100_000)
    source_url: str = Field(min_length=8, max_length=2000)
    event_time: datetime
    published_at: datetime
    available_at: datetime | None = None
    entity_evidence: list[str] = Field(min_length=1, max_length=20)
    raw_version: str = Field(default="v1", pattern=r"^[A-Za-z0-9_.-]{1,32}$")
    supersedes: str | None = Field(default=None, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_url")
    @classmethod
    def source_url_must_be_http(cls, value: str) -> str:
        if not value.startswith(("https://", "http://")):
            raise ValueError("source_url must use http or https")
        return value

    @model_validator(mode="after")
    def timestamps_must_be_timezone_aware(self) -> RawKnowledgeItem:
        for field_name in ("event_time", "published_at", "available_at"):
            value = getattr(self, field_name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{field_name} must include a timezone")
        return self


class SourceBatch(BaseModel):
    source_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,63}$")
    source_rank: int = Field(ge=1, le=5)
    license_name: str = Field(min_length=2, max_length=128)
    cursor_before: str | None = None
    cursor_after: str | None = None
    fetched_at: datetime
    records: list[RawKnowledgeItem] = Field(default_factory=list)


class KnowledgeEvent(BaseModel):
    event_id: str
    canonical_key: str
    symbol: str
    event_type: str
    title: str
    content: str
    event_time: datetime
    published_at: datetime
    ingested_at: datetime
    available_at: datetime
    source_id: str
    source_record_id: str
    source_url: str
    source_rank: int
    content_hash: str
    raw_version: str
    extraction_version: str
    status: KnowledgeEventStatus
    raw_locator: str
    evidence_refs: list[str] = Field(default_factory=list)
    entity_evidence: list[str] = Field(default_factory=list)
    supersedes: str | None = None
    conflict_group: str | None = None
    rejection_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeIngestionResult(BaseModel):
    source_id: str
    cursor_before: str | None = None
    cursor_after: str | None = None
    raw_rows: int = 0
    candidates: int = 0
    active: int = 0
    rejected: int = 0
    duplicates: int = 0
    conflicts: int = 0
    snapshot_id: int | None = None
    warnings: list[str] = Field(default_factory=list)
