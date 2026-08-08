from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


TERMINAL_JOB_STATUSES = {
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}


class AdmissionRejected(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        status_code: int = 429,
        retry_after_seconds: int = 5,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


class JobSnapshot(BaseModel):
    run_id: str
    status: JobStatus
    question: str
    tenant_id: str
    user_id: str
    session_id: str
    queue_class: str = "interactive"
    priority: int = 100
    attempt_no: int = Field(ge=0)
    cancel_requested: bool
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None
    result_available: bool = False
    queue_wait_ms: int | None = None
    execution_ms: int | None = None
    total_ms: int | None = None


class ClaimedJob(BaseModel):
    run_id: str
    question: str
    tenant_id: str
    user_id: str
    session_id: str
    queue_class: str = "interactive"
    priority: int = 100
    attempt_no: int
    lease_owner: str
    lease_expires_at: datetime


class JobEvent(BaseModel):
    event_id: int
    source: str
    event_type: str
    node_name: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
