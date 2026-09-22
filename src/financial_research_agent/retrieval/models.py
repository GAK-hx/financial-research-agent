from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from financial_research_agent.domain.models import ToolResult


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_topic(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())[:200]


class CacheDecision(StrEnum):
    FRESH = "fresh"
    PARTIAL = "partial"
    STALE = "stale"
    INFLIGHT = "inflight"
    MISS = "miss"


class ArtifactVisibility(StrEnum):
    PUBLIC = "public"
    TENANT = "tenant"


class WorkStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    SUCCEEDED = "succeeded"
    RETRY_WAIT = "retry_wait"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AtomicQueryKey(BaseModel):
    stock_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    domain: str = Field(min_length=1, max_length=64)
    topic: str = Field(default="", max_length=200)
    window_start: datetime | None = None
    window_end: datetime | None = None
    provider_policy_version: str = Field(default="retrieval_v1", max_length=64)
    visibility: ArtifactVisibility = ArtifactVisibility.PUBLIC
    tenant_id: str | None = Field(default=None, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_scope(self) -> AtomicQueryKey:
        self.topic = normalize_topic(self.topic)
        if self.window_start and self.window_end and self.window_end < self.window_start:
            raise ValueError("atomic query window is invalid")
        if self.visibility == ArtifactVisibility.TENANT and not self.tenant_id:
            raise ValueError("tenant-visible query requires tenant_id")
        if self.visibility == ArtifactVisibility.PUBLIC:
            self.tenant_id = None
        return self

    @property
    def cache_key(self) -> str:
        return canonical_hash(self.model_dump(mode="json", exclude_none=True))


class RetrievalSnapshot(BaseModel):
    snapshot_id: str
    atomic_key: AtomicQueryKey
    key_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    generation: int = Field(default=1, ge=1)
    source_version: str = Field(min_length=1, max_length=128)
    result: ToolResult
    evidence_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    watermark: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    refreshed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime

    @property
    def is_fresh(self) -> bool:
        return self.expires_at > datetime.now(timezone.utc)


class AnalysisArtifact(BaseModel):
    artifact_id: str
    analysis_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    analysis_type: str = Field(min_length=1, max_length=64)
    subjects: list[str] = Field(min_length=1, max_length=20)
    snapshot_dependencies: dict[str, str] = Field(default_factory=dict)
    skill_versions: list[str] = Field(default_factory=list)
    model_id: str = Field(max_length=128)
    prompt_version: str = Field(max_length=64)
    policy_version: str = Field(max_length=64)
    payload: dict[str, Any]
    validated: bool = False
    visibility: ArtifactVisibility = ArtifactVisibility.PUBLIC
    tenant_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime

    @model_validator(mode="after")
    def validate_visibility(self) -> AnalysisArtifact:
        if self.visibility == ArtifactVisibility.TENANT and not self.tenant_id:
            raise ValueError("tenant-visible artifact requires tenant_id")
        if self.visibility == ArtifactVisibility.PUBLIC:
            self.tenant_id = None
        return self


class PresentationEnvelope(BaseModel):
    run_id: str
    tenant_id: str
    user_id: str
    session_id: str
    analysis_artifact_ids: list[str] = Field(default_factory=list)
    cache_decisions: dict[str, CacheDecision] = Field(default_factory=dict)
    refresh_performed: bool = False
    data_as_of: date | datetime | None = None
    lineage: dict[str, list[str]] = Field(default_factory=dict)


class CacheResolution(BaseModel):
    decision: CacheDecision
    key_hash: str
    work_unit_id: str | None = None
    snapshot: RetrievalSnapshot | None = None
    lease_owner: str | None = None
    retry_after_seconds: float | None = Field(default=None, ge=0)
    stale_while_refresh: bool = False


class RetrievalMetrics(BaseModel):
    decisions: dict[str, int] = Field(default_factory=dict)
    external_calls_saved: int = 0
    inflight_joins: int = 0
    new_documents: int = 0
    updated_documents: int = 0
    unchanged_documents: int = 0


def build_analysis_key(
    *,
    analysis_type: str,
    subjects: list[str],
    snapshot_dependencies: dict[str, str],
    skill_versions: list[str],
    model_id: str,
    prompt_version: str,
    policy_version: str,
) -> str:
    return canonical_hash(
        {
            "analysis_type": analysis_type,
            "subjects": sorted(subjects),
            "snapshot_dependencies": dict(sorted(snapshot_dependencies.items())),
            "skill_versions": sorted(skill_versions),
            "model_id": model_id,
            "prompt_version": prompt_version,
            "policy_version": policy_version,
        }
    )


def public_visibility_for_domain(domain: str) -> Literal["public", "tenant"]:
    return "tenant" if domain in {"memory", "private_upload"} else "public"
