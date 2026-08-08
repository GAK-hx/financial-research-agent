from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


IDENTITY_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$"
MEMORY_KEY_PATTERN = r"^[a-z][a-z0-9_]{2,63}$"


class MemoryKind(StrEnum):
    SESSION = "session"
    PREFERENCE = "preference"
    EPISODIC = "episodic"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"
    EXPIRED = "expired"


class MemoryScope(BaseModel):
    tenant_id: str = Field(default="local", pattern=IDENTITY_PATTERN)
    user_id: str = Field(default="local", pattern=IDENTITY_PATTERN)
    session_id: str = Field(default="default", pattern=IDENTITY_PATTERN)


class MemorySource(BaseModel):
    source_type: Literal[
        "query_spec",
        "explicit_user_confirmation",
        "api",
        "validated_run",
        "reflection",
    ]
    source_id: str = Field(min_length=1, max_length=128)
    run_id: str | None = Field(default=None, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CandidateMemory(BaseModel):
    kind: MemoryKind
    key: str = Field(pattern=MEMORY_KEY_PATTERN)
    value: Any
    source: MemorySource
    ttl_seconds: int | None = Field(default=None, ge=60, le=31_536_000)
    explicitly_confirmed: bool = False
    validation_passed: bool = False

    @model_validator(mode="after")
    def preference_requires_confirmation(self) -> CandidateMemory:
        if self.kind == MemoryKind.PREFERENCE and not self.explicitly_confirmed:
            raise ValueError("preference memory requires explicit confirmation")
        if self.kind == MemoryKind.EPISODIC and not self.validation_passed:
            raise ValueError("episodic memory requires a validated terminal run")
        return self


class MemoryRecord(BaseModel):
    memory_id: str
    scope: MemoryScope
    kind: MemoryKind
    key: str
    value: Any
    version: int = Field(ge=1)
    status: MemoryStatus
    source: MemorySource
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class MemoryAuditEvent(BaseModel):
    audit_id: str
    memory_id: str | None = None
    scope: MemoryScope
    action: Literal[
        "create",
        "update",
        "read",
        "delete",
        "expire",
        "reject",
        "reflect",
    ]
    reason_code: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ContextPolicy(BaseModel):
    policy_id: str = Field(pattern=MEMORY_KEY_PATTERN)
    node_name: Literal[
        "interpret",
        "select_skill",
        "plan",
        "generate_report",
        "revise_report",
    ]
    max_input_tokens: int = Field(ge=256)
    reserved_output_tokens: int = Field(ge=0)
    max_session_items: int = Field(default=8, ge=0, le=32)
    max_preference_items: int = Field(default=8, ge=0, le=32)
    max_episodic_items: int = Field(default=4, ge=0, le=16)
    max_knowledge_items: int = Field(default=8, ge=0, le=32)
    allow_model_summary: bool = False
    max_summary_depth: int = Field(default=1, ge=0, le=1)
    overflow_action: Literal["trim", "reject"] = "trim"


class ContextItemRef(BaseModel):
    item_type: str
    item_id: str
    priority: int = Field(ge=0, le=100)
    content_hash: str
    source_locator: str | None = None
    version: str | None = None
    selection_reason: str = "required_by_context_policy"
    estimated_tokens: int = Field(default=0, ge=0)


class MemoryVersion(BaseModel):
    memory_id: str
    version: int = Field(ge=1)
    status: MemoryStatus
    value: Any
    source: MemorySource
    created_at: datetime


class ContextManifest(BaseModel):
    manifest_id: str
    run_id: str
    node_name: str
    context_policy_id: str
    skill_versions: list[str] = Field(default_factory=list)
    policy_version: str
    token_estimator_version: str = "utf8_bytes_v1"
    included: list[ContextItemRef] = Field(default_factory=list)
    trimmed: list[ContextItemRef] = Field(default_factory=list)
    token_estimate_before: int = Field(ge=0)
    token_estimate_after: int = Field(ge=0)
    compression_ratio: float = Field(ge=0, le=1)
    summary_id: str | None = None
    summary_depth: int = Field(default=0, ge=0, le=1)
    summary_input_hash: str | None = None
    summary_source_refs: list[ContextItemRef] = Field(default_factory=list)
    evidence_protection_hash: str | None = None
    evidence_protection_passed: bool = True
    warnings: list[str] = Field(default_factory=list)
    built_at: datetime


class BuiltContext(BaseModel):
    payload: dict[str, Any]
    manifest: ContextManifest
