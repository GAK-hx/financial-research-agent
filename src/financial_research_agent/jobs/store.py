from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from financial_research_agent.jobs.models import (
    ClaimedJob,
    AdmissionRejected,
    JobEvent,
    JobSnapshot,
    JobStatus,
    TERMINAL_JOB_STATUSES,
)
from financial_research_agent.config import Settings
from financial_research_agent.observability import redact
from financial_research_agent.persistence.models import (
    AdmissionAuditRecord,
    ContextManifestRecord,
    JobEventRecord,
    ModelCallRecord,
    NodeAttemptRecord,
    ResearchJobRecord,
    RunEventRecord,
    RunRecord,
    ToolCallRecord,
    TenantScheduleRecord,
)
from financial_research_agent.persistence.store import canonical_hash


class JobConflict(RuntimeError):
    pass


def _snapshot(record: ResearchJobRecord) -> JobSnapshot:
    terminal_at = record.finished_at or record.updated_at
    return JobSnapshot(
        run_id=record.run_id,
        status=JobStatus(record.status),
        question=record.question,
        tenant_id=record.tenant_id,
        user_id=record.user_id,
        session_id=record.session_id,
        queue_class=record.queue_class,
        priority=record.priority,
        attempt_no=record.attempt_no,
        cancel_requested=record.cancel_requested,
        lease_owner=record.lease_owner,
        lease_expires_at=record.lease_expires_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        last_error=record.last_error,
        result_available=record.result_payload is not None,
        queue_wait_ms=(
            int((record.started_at - record.created_at).total_seconds() * 1000)
            if record.started_at is not None
            else None
        ),
        execution_ms=(
            int((record.finished_at - record.started_at).total_seconds() * 1000)
            if record.finished_at is not None and record.started_at is not None
            else None
        ),
        total_ms=int((terminal_at - record.created_at).total_seconds() * 1000),
    )


def _safe_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _safe_payload(item)
            for key, item in value.items()
            if key.lower()
            not in {
                "reasoning",
                "reasoning_content",
                "chain_of_thought",
                "hidden_reasoning",
                "prompt",
                "messages",
            }
        }
    if isinstance(value, list):
        return [_safe_payload(item) for item in value]
    return value


class JobStore:
    def __init__(
        self,
        engine: AsyncEngine,
        sessions: async_sessionmaker,
        *,
        worker_id: str | None = None,
        lease_seconds: int = 180,
        settings: Settings | None = None,
    ) -> None:
        self.engine = engine
        self.sessions = sessions
        self.worker_id = worker_id or f"job-worker-{uuid4().hex}"
        self.lease_seconds = lease_seconds
        self.settings = settings or Settings()

    async def close(self) -> None:
        await self.engine.dispose()

    async def enqueue(
        self,
        *,
        question: str,
        tenant_id: str,
        user_id: str,
        session_id: str,
        idempotency_key: str,
        queue_class: str = "interactive",
        run_id: str | None = None,
    ) -> tuple[JobSnapshot, bool]:
        if queue_class not in {"interactive", "batch"}:
            raise JobConflict("INVALID_QUEUE_CLASS")
        run_id = run_id or uuid4().hex
        request = {
            "question": question,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "session_id": session_id,
            "queue_class": queue_class,
        }
        request_hash = canonical_hash(request)
        reject_code: str | None = None
        async with self.sessions.begin() as session:
            existing = await session.scalar(
                select(ResearchJobRecord).where(
                    ResearchJobRecord.tenant_id == tenant_id,
                    ResearchJobRecord.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise JobConflict(
                        "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_INPUT"
                    )
                return _snapshot(existing), False
            await session.execute(
                text(
                    "SELECT pg_advisory_xact_lock(hashtext(:lock_key))"
                ),
                {"lock_key": "financial_agent:job_admission"},
            )
            reject_code = await self._queue_limit_code(
                session, tenant_id, user_id
            )
            if reject_code is not None:
                session.add(
                    AdmissionAuditRecord(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        decision="rejected",
                        reason_code=reject_code,
                        retry_after_seconds=(
                            self.settings.job_admission_retry_after_seconds
                        ),
                    )
                )
                await session.flush()
            else:
                priority = 100 if queue_class == "interactive" else 10
                inserted = await session.scalar(
                    pg_insert(ResearchJobRecord)
                    .values(
                        run_id=run_id,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        question=question,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        session_id=session_id,
                        queue_class=queue_class,
                        priority=priority,
                        status=JobStatus.QUEUED.value,
                    )
                    .on_conflict_do_nothing()
                    .returning(ResearchJobRecord.run_id)
                )
                if inserted is None:
                    existing = await session.scalar(
                        select(ResearchJobRecord).where(
                            ResearchJobRecord.tenant_id == tenant_id,
                            ResearchJobRecord.idempotency_key
                            == idempotency_key,
                        )
                    )
                    if existing is None:
                        raise JobConflict("IDEMPOTENCY_LOOKUP_LOST")
                    if existing.request_hash != request_hash:
                        raise JobConflict(
                            "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_INPUT"
                        )
                    return _snapshot(existing), False
                record = await session.get(ResearchJobRecord, run_id)
                assert record is not None
                session.add(
                    AdmissionAuditRecord(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        decision="accepted",
                    )
                )
                await self._append_event(
                    session,
                    record,
                    "job_queued",
                    {
                        "status": JobStatus.QUEUED.value,
                        "queue_class": queue_class,
                        "priority": priority,
                    },
                )
                await session.flush()
                await session.refresh(record)
                created_snapshot = _snapshot(record)
        if reject_code is not None:
            raise AdmissionRejected(
                reject_code,
                retry_after_seconds=(
                    self.settings.job_admission_retry_after_seconds
                ),
            )
        return created_snapshot, True

    async def get(
        self,
        run_id: str,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        tenant_admin: bool = False,
    ) -> JobSnapshot | None:
        async with self.sessions() as session:
            record = await session.scalar(
                self._scoped_job_query(
                    run_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    tenant_admin=tenant_admin,
                )
            )
            return _snapshot(record) if record is not None else None

    async def result(
        self,
        run_id: str,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        tenant_admin: bool = False,
    ) -> dict[str, Any] | None:
        async with self.sessions() as session:
            record = await session.scalar(
                self._scoped_job_query(
                    run_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    tenant_admin=tenant_admin,
                )
            )
            return record.result_payload if record is not None else None

    async def claim(self) -> ClaimedJob | None:
        now = datetime.now(timezone.utc)
        async with self.sessions.begin() as session:
            await session.execute(
                text(
                    "SELECT pg_advisory_xact_lock(hashtext(:lock_key))"
                ),
                {"lock_key": "financial_agent:job_claim"},
            )
            active_filter = and_(
                ResearchJobRecord.status == JobStatus.RUNNING.value,
                ResearchJobRecord.lease_expires_at.is_not(None),
                ResearchJobRecord.lease_expires_at > now,
            )
            active_rows = (
                await session.execute(
                    select(
                        ResearchJobRecord.tenant_id,
                        ResearchJobRecord.user_id,
                        func.count(ResearchJobRecord.run_id),
                    )
                    .where(active_filter)
                    .group_by(
                        ResearchJobRecord.tenant_id,
                        ResearchJobRecord.user_id,
                    )
                )
            ).all()
            if sum(int(row[2]) for row in active_rows) >= (
                self.settings.job_global_running_limit
            ):
                return None
            tenant_active: dict[str, int] = {}
            user_active: dict[tuple[str, str], int] = {}
            for tenant, user, count in active_rows:
                tenant_active[tenant] = tenant_active.get(tenant, 0) + int(
                    count
                )
                user_active[(tenant, user)] = int(count)

            candidates = (
                await session.execute(
                    select(ResearchJobRecord)
                    .where(
                        ResearchJobRecord.cancel_requested.is_(False),
                        ResearchJobRecord.available_at <= now,
                        or_(
                            ResearchJobRecord.status
                            == JobStatus.QUEUED.value,
                            and_(
                                ResearchJobRecord.status
                                == JobStatus.RUNNING.value,
                                ResearchJobRecord.lease_expires_at.is_not(
                                    None
                                ),
                                ResearchJobRecord.lease_expires_at <= now,
                            ),
                        ),
                    )
                    .order_by(
                        ResearchJobRecord.priority.desc(),
                        ResearchJobRecord.available_at,
                        ResearchJobRecord.created_at,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(self.settings.job_claim_scan_limit)
                )
            ).scalars().all()
            if not candidates:
                return None
            schedule_rows = (
                await session.execute(select(TenantScheduleRecord))
            ).scalars().all()
            last_claimed = {
                row.tenant_id: row.last_claimed_at for row in schedule_rows
            }
            eligible: list[ResearchJobRecord] = []
            tenant_seen: set[str] = set()
            for candidate in candidates:
                if candidate.tenant_id in tenant_seen:
                    continue
                if tenant_active.get(candidate.tenant_id, 0) >= (
                    self.settings.job_tenant_running_limit
                ):
                    continue
                if user_active.get(
                    (candidate.tenant_id, candidate.user_id), 0
                ) >= self.settings.job_user_running_limit:
                    continue
                tenant_seen.add(candidate.tenant_id)
                eligible.append(candidate)
            if not eligible:
                return None
            epoch = datetime.min.replace(tzinfo=timezone.utc)
            record = min(
                eligible,
                key=lambda item: (
                    -item.priority,
                    last_claimed.get(item.tenant_id) or epoch,
                    item.created_at,
                ),
            )
            recovered = record.status == JobStatus.RUNNING.value
            record.status = JobStatus.RUNNING.value
            record.lease_owner = self.worker_id
            record.lease_expires_at = now + timedelta(
                seconds=self.lease_seconds
            )
            record.attempt_no += 1
            record.started_at = record.started_at or now
            record.updated_at = now
            await self._append_event(
                session,
                record,
                "job_reclaimed" if recovered else "job_claimed",
                {
                    "worker_id": self.worker_id,
                    "attempt_no": record.attempt_no,
                    "lease_expires_at": record.lease_expires_at.isoformat(),
                },
            )
            await session.execute(
                pg_insert(TenantScheduleRecord)
                .values(
                    tenant_id=record.tenant_id,
                    claim_count=1,
                    last_claimed_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[TenantScheduleRecord.tenant_id],
                    set_={
                        "claim_count": TenantScheduleRecord.claim_count + 1,
                        "last_claimed_at": now,
                        "updated_at": now,
                    },
                )
            )
            return ClaimedJob(
                run_id=record.run_id,
                question=record.question,
                tenant_id=record.tenant_id,
                user_id=record.user_id,
                session_id=record.session_id,
                queue_class=record.queue_class,
                priority=record.priority,
                attempt_no=record.attempt_no,
                lease_owner=self.worker_id,
                lease_expires_at=record.lease_expires_at,
            )

    async def renew(self, run_id: str) -> bool:
        now = datetime.now(timezone.utc)
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(ResearchJobRecord)
                .where(
                    ResearchJobRecord.run_id == run_id,
                    ResearchJobRecord.status == JobStatus.RUNNING.value,
                    ResearchJobRecord.lease_owner == self.worker_id,
                )
                .values(
                    lease_expires_at=now
                    + timedelta(seconds=self.lease_seconds),
                    updated_at=now,
                )
            )
            return result.rowcount == 1

    async def complete(
        self,
        run_id: str,
        *,
        status: JobStatus,
        result_payload: dict[str, Any],
        last_error: str | None = None,
    ) -> None:
        if status not in TERMINAL_JOB_STATUSES:
            raise ValueError("job completion requires a terminal status")
        now = datetime.now(timezone.utc)
        async with self.sessions.begin() as session:
            record = await session.get(
                ResearchJobRecord, run_id, with_for_update=True
            )
            if record is None:
                raise JobConflict("JOB_NOT_FOUND")
            if record.status in {
                item.value for item in TERMINAL_JOB_STATUSES
            }:
                if (
                    record.status == status.value
                    and record.result_payload == result_payload
                ):
                    return
                raise JobConflict("JOB_ALREADY_TERMINAL")
            if (
                record.lease_owner != self.worker_id
                or record.status != JobStatus.RUNNING.value
            ):
                raise JobConflict("JOB_LEASE_NOT_OWNED")
            for item in result_payload.get("tool_status", []):
                await self._append_event(
                    session,
                    record,
                    "tool_completed"
                    if item.get("success")
                    else "tool_failed",
                    _safe_payload(redact(item)),
                )
            budget = result_payload.get("budget")
            if budget:
                await self._append_event(
                    session,
                    record,
                    "budget_snapshot",
                    _safe_payload(redact(budget)),
                )
            record.status = status.value
            record.result_payload = result_payload
            record.last_error = last_error[:512] if last_error else None
            record.finished_at = now
            record.lease_owner = None
            record.lease_expires_at = None
            record.updated_at = now
            await self._append_event(
                session,
                record,
                "job_terminal",
                {
                    "status": status.value,
                    "success": bool(result_payload.get("success")),
                },
            )

    async def interrupt(self, run_id: str, error: str) -> None:
        now = datetime.now(timezone.utc)
        async with self.sessions.begin() as session:
            record = await session.get(
                ResearchJobRecord, run_id, with_for_update=True
            )
            if record is None:
                raise JobConflict("JOB_NOT_FOUND")
            if record.lease_owner != self.worker_id:
                raise JobConflict("JOB_LEASE_NOT_OWNED")
            record.status = JobStatus.INTERRUPTED.value
            record.last_error = error[:512]
            record.lease_owner = None
            record.lease_expires_at = None
            record.updated_at = now
            await self._append_event(
                session,
                record,
                "job_interrupted",
                {"error": error[:256]},
            )

    async def request_cancel(
        self,
        run_id: str,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        tenant_admin: bool = False,
    ) -> JobSnapshot:
        now = datetime.now(timezone.utc)
        async with self.sessions.begin() as session:
            record = await session.scalar(
                self._scoped_job_query(
                    run_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    tenant_admin=tenant_admin,
                ).with_for_update()
            )
            if record is None:
                raise JobConflict("JOB_NOT_FOUND")
            status = JobStatus(record.status)
            if status in TERMINAL_JOB_STATUSES:
                if status == JobStatus.CANCELLED:
                    return _snapshot(record)
                raise JobConflict("ILLEGAL_CANCEL_TRANSITION")
            if not record.cancel_requested:
                record.cancel_requested = True
                if status in {
                    JobStatus.QUEUED,
                    JobStatus.INTERRUPTED,
                }:
                    record.status = JobStatus.CANCELLED.value
                    record.finished_at = now
                run = await session.get(RunRecord, run_id)
                if run is not None:
                    run.cancel_requested = True
                    run.updated_at = now
                await self._append_event(
                    session,
                    record,
                    "cancel_requested",
                    {"status": record.status},
                )
            record.updated_at = now
            return _snapshot(record)

    async def resume(
        self,
        run_id: str,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        tenant_admin: bool = False,
    ) -> JobSnapshot:
        now = datetime.now(timezone.utc)
        rejected: str | None = None
        resumed: JobSnapshot | None = None
        async with self.sessions.begin() as session:
            record = await session.scalar(
                self._scoped_job_query(
                    run_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    tenant_admin=tenant_admin,
                ).with_for_update()
            )
            if record is None:
                raise JobConflict("JOB_NOT_FOUND")
            status = JobStatus(record.status)
            if status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                return _snapshot(record)
            if status != JobStatus.INTERRUPTED:
                raise JobConflict("ILLEGAL_RESUME_TRANSITION")
            await session.execute(
                text(
                    "SELECT pg_advisory_xact_lock(hashtext(:lock_key))"
                ),
                {"lock_key": "financial_agent:job_admission"},
            )
            rejected = await self._queue_limit_code(
                session, record.tenant_id, record.user_id
            )
            if rejected is not None:
                session.add(
                    AdmissionAuditRecord(
                        tenant_id=record.tenant_id,
                        user_id=record.user_id,
                        decision="rejected",
                        reason_code=rejected,
                        retry_after_seconds=(
                            self.settings.job_admission_retry_after_seconds
                        ),
                    )
                )
            else:
                record.status = JobStatus.QUEUED.value
                record.cancel_requested = False
                record.available_at = now
                record.lease_owner = None
                record.lease_expires_at = None
                record.last_error = None
                record.updated_at = now
                run = await session.get(RunRecord, run_id)
                if run is not None:
                    run.cancel_requested = False
                    run.status = JobStatus.RUNNING.value
                    run.updated_at = now
                await self._append_event(
                    session, record, "job_resumed", {"status": "queued"}
                )
                resumed = _snapshot(record)
        if rejected is not None:
            raise AdmissionRejected(
                rejected,
                retry_after_seconds=(
                    self.settings.job_admission_retry_after_seconds
                ),
            )
        assert resumed is not None
        return resumed

    async def events(
        self,
        run_id: str,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        tenant_admin: bool = False,
    ) -> list[JobEvent]:
        async with self.sessions() as session:
            if await session.scalar(
                self._scoped_job_query(
                    run_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    tenant_admin=tenant_admin,
                )
            ) is None:
                raise JobConflict("JOB_NOT_FOUND")
            job_rows = (
                await session.execute(
                    select(JobEventRecord)
                    .where(JobEventRecord.run_id == run_id)
                    .order_by(JobEventRecord.created_at, JobEventRecord.id)
                )
            ).scalars().all()
            run_rows = (
                await session.execute(
                    select(RunEventRecord)
                    .where(RunEventRecord.run_id == run_id)
                    .order_by(RunEventRecord.created_at, RunEventRecord.id)
                )
            ).scalars().all()
        combined: list[tuple[datetime, int, str, Any]] = [
            (item.created_at, item.id, "job", item) for item in job_rows
        ] + [
            (item.created_at, item.id, "run", item) for item in run_rows
        ]
        combined.sort(key=lambda item: (item[0], item[2], item[1]))
        events: list[JobEvent] = []
        for index, (_, _, source, item) in enumerate(combined, start=1):
            events.append(
                JobEvent(
                    event_id=index,
                    source=source,
                    event_type=item.event_type,
                    node_name=getattr(item, "node_name", None),
                    payload=_safe_payload(redact(dict(item.payload or {}))),
                    created_at=item.created_at,
                )
            )
        return events

    async def trace(
        self,
        run_id: str,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        tenant_admin: bool = False,
    ) -> dict[str, Any]:
        async with self.sessions() as session:
            job = await session.scalar(
                self._scoped_job_query(
                    run_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    tenant_admin=tenant_admin,
                )
            )
            if job is None:
                raise JobConflict("JOB_NOT_FOUND")
            attempts = (
                await session.execute(
                    select(NodeAttemptRecord)
                    .where(NodeAttemptRecord.run_id == run_id)
                    .order_by(
                        NodeAttemptRecord.started_at,
                        NodeAttemptRecord.attempt_no,
                    )
                )
            ).scalars().all()
            model_calls = (
                await session.execute(
                    select(ModelCallRecord)
                    .where(ModelCallRecord.run_id == run_id)
                    .order_by(ModelCallRecord.created_at)
                )
            ).scalars().all()
            tool_calls = (
                await session.execute(
                    select(ToolCallRecord)
                    .where(ToolCallRecord.run_id == run_id)
                    .order_by(ToolCallRecord.created_at)
                )
            ).scalars().all()
            contexts = (
                await session.execute(
                    select(ContextManifestRecord)
                    .where(ContextManifestRecord.run_id == run_id)
                    .order_by(ContextManifestRecord.created_at)
                )
            ).scalars().all()
        return {
            "run_id": run_id,
            "status": job.status,
            "attempt_no": job.attempt_no,
            "nodes": [
                {
                    "node_name": item.node_name,
                    "attempt_no": item.attempt_no,
                    "status": item.status,
                    "error_code": item.error_code,
                    "started_at": item.started_at,
                    "finished_at": item.finished_at,
                }
                for item in attempts
            ],
            "model_calls": [
                {
                    "node_name": item.node_name,
                    "provider": item.provider,
                    "model_name": item.model_name,
                    "status": item.status,
                    "attempt_count": item.attempt_count,
                    "input_tokens": item.input_tokens,
                    "output_tokens": item.output_tokens,
                    "total_tokens": item.total_tokens,
                    "cost_microunits": item.cost_microunits,
                    "error_code": item.error_code,
                }
                for item in model_calls
            ],
            "tool_calls": [
                {
                    "task_id": item.task_id,
                    "tool_name": item.tool_name,
                    "status": item.status,
                    "attempt_count": item.attempt_count,
                    "error_code": item.error_code,
                }
                for item in tool_calls
            ],
            "contexts": [
                {
                    "node_name": item.node_name,
                    "context_policy_id": item.context_policy_id,
                    "skill_versions": item.skill_versions,
                    "token_estimate_before": item.token_estimate_before,
                    "token_estimate_after": item.token_estimate_after,
                    "compression_ratio": item.compression_ratio,
                    "evidence_protection_passed": (
                        item.evidence_protection_passed
                    ),
                }
                for item in contexts
            ],
        }

    async def metrics(self) -> dict[str, Any]:
        async with self.sessions() as session:
            status_rows = (
                await session.execute(
                    select(
                        ResearchJobRecord.status,
                        func.count(ResearchJobRecord.run_id),
                    ).group_by(ResearchJobRecord.status)
                )
            ).all()
            model = (
                await session.execute(
                    select(
                        func.count(ModelCallRecord.id),
                        func.coalesce(func.sum(ModelCallRecord.total_tokens), 0),
                        func.coalesce(
                            func.sum(ModelCallRecord.cost_microunits), 0
                        ),
                    )
                )
            ).one()
            tool_count = await session.scalar(
                select(func.count(ToolCallRecord.id))
            )
            admission_rows = (
                await session.execute(
                    select(
                        AdmissionAuditRecord.decision,
                        AdmissionAuditRecord.reason_code,
                        func.count(AdmissionAuditRecord.id),
                    ).group_by(
                        AdmissionAuditRecord.decision,
                        AdmissionAuditRecord.reason_code,
                    )
                )
            ).all()
            oldest_queued = await session.scalar(
                select(func.min(ResearchJobRecord.created_at)).where(
                    ResearchJobRecord.status == JobStatus.QUEUED.value
                )
            )
            active_workers = await session.scalar(
                select(func.count(func.distinct(ResearchJobRecord.lease_owner))).where(
                    ResearchJobRecord.status == JobStatus.RUNNING.value,
                    ResearchJobRecord.lease_owner.is_not(None),
                )
            )
        current = datetime.now(timezone.utc)
        oldest_age = (
            max(0.0, (current - oldest_queued).total_seconds())
            if oldest_queued is not None
            else 0.0
        )
        return {
            "jobs": {status: count for status, count in status_rows},
            "model_calls": int(model[0] or 0),
            "model_tokens": int(model[1] or 0),
            "model_cost_microunits": int(model[2] or 0),
            "tool_calls": int(tool_count or 0),
            "admission": {
                f"{decision}:{reason or 'none'}": int(count)
                for decision, reason, count in admission_rows
            },
            "oldest_queue_age_seconds": oldest_age,
            "active_workers": int(active_workers or 0),
        }

    async def _queue_limit_code(
        self, session, tenant_id: str, user_id: str
    ) -> str | None:
        queued = JobStatus.QUEUED.value
        counter = func.count(ResearchJobRecord.run_id)
        global_count, tenant_count, user_count = (
            await session.execute(
                select(
                    counter,
                    counter.filter(
                        ResearchJobRecord.tenant_id == tenant_id
                    ),
                    counter.filter(
                        ResearchJobRecord.tenant_id == tenant_id,
                        ResearchJobRecord.user_id == user_id,
                    ),
                ).where(ResearchJobRecord.status == queued)
            )
        ).one()
        global_count = int(global_count or 0)
        tenant_count = int(tenant_count or 0)
        user_count = int(user_count or 0)
        if global_count >= self.settings.job_global_queue_limit:
            return "GLOBAL_QUEUE_LIMIT"
        if tenant_count >= self.settings.job_tenant_queue_limit:
            return "TENANT_QUEUE_LIMIT"
        if user_count >= self.settings.job_user_queue_limit:
            return "USER_QUEUE_LIMIT"
        return None

    @staticmethod
    def _scoped_job_query(
        run_id: str,
        *,
        tenant_id: str | None,
        user_id: str | None,
        tenant_admin: bool,
    ):
        query = select(ResearchJobRecord).where(
            ResearchJobRecord.run_id == run_id
        )
        if tenant_id is not None:
            query = query.where(ResearchJobRecord.tenant_id == tenant_id)
        if user_id is not None and not tenant_admin:
            query = query.where(ResearchJobRecord.user_id == user_id)
        return query

    @staticmethod
    async def _append_event(
        session,
        record: ResearchJobRecord,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        record.event_sequence += 1
        session.add(
            JobEventRecord(
                run_id=record.run_id,
                sequence=record.event_sequence,
                event_type=event_type,
                payload=_safe_payload(redact(payload)),
            )
        )
