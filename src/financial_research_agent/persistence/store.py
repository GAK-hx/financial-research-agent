from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from financial_research_agent.persistence.models import (
    ArtifactRefRecord,
    ModelCallRecord,
    NodeAttemptRecord,
    RunEventRecord,
    RunRecord,
    TerminalResultRecord,
    ToolCallRecord,
)


class PersistenceConflict(RuntimeError):
    pass


class OperationInProgress(PersistenceConflict):
    pass


@dataclass(frozen=True)
class CallReservation:
    execute: bool
    call_id: str
    result_payload: dict[str, Any] | None = None


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class BusinessStore:
    def __init__(
        self,
        engine: AsyncEngine,
        sessions: async_sessionmaker,
        *,
        worker_id: str | None = None,
        lease_seconds: int = 30,
    ) -> None:
        self.engine = engine
        self.sessions = sessions
        self.worker_id = worker_id or f"worker-{uuid4().hex}"
        self.lease_seconds = lease_seconds

    async def close(self) -> None:
        await self.engine.dispose()

    async def create_run(
        self,
        run_id: str,
        thread_id: str,
        question: str,
        runtime: str,
        *,
        tenant_id: str = "local",
        user_id: str = "local",
        session_id: str = "default",
    ) -> bool:
        async with self.sessions.begin() as session:
            inserted = await session.scalar(
                pg_insert(RunRecord)
                .values(
                    id=run_id,
                    thread_id=thread_id,
                    question=question,
                    status="running",
                    runtime=runtime,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    session_id=session_id,
                )
                .on_conflict_do_nothing()
                .returning(RunRecord.id)
            )
            if inserted is None:
                existing = await session.get(RunRecord, run_id)
                if existing is None:
                    raise PersistenceConflict("THREAD_ID_ALREADY_IN_USE")
                if (
                    existing.thread_id != thread_id
                    or existing.question != question
                    or existing.tenant_id != tenant_id
                    or existing.user_id != user_id
                    or existing.session_id != session_id
                ):
                    raise PersistenceConflict("RUN_ID_REUSED_WITH_DIFFERENT_INPUT")
                return False
        await self.append_event(run_id, "run_created", payload={"runtime": runtime})
        return True

    async def get_run(self, run_id: str) -> RunRecord | None:
        async with self.sessions() as session:
            return await session.get(RunRecord, run_id)

    async def request_cancel(self, run_id: str) -> bool:
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(RunRecord)
                .where(RunRecord.id == run_id, RunRecord.cancel_requested.is_(False))
                .values(cancel_requested=True, updated_at=func.now())
                .returning(RunRecord.id)
            )
            changed = result.scalar_one_or_none() is not None
        if changed:
            await self.append_event(run_id, "cancel_requested")
        return changed

    async def mark_run_status(self, run_id: str, status: str) -> None:
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(RunRecord)
                .where(RunRecord.id == run_id)
                .values(status=status, updated_at=func.now())
            )
            if result.rowcount != 1:
                raise PersistenceConflict("RUN_NOT_FOUND")

    async def is_cancel_requested(self, run_id: str) -> bool:
        async with self.sessions() as session:
            value = await session.scalar(
                select(RunRecord.cancel_requested).where(RunRecord.id == run_id)
            )
            return bool(value)

    async def append_event(
        self,
        run_id: str,
        event_type: str,
        *,
        node_name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> int:
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(RunRecord)
                .where(RunRecord.id == run_id)
                .values(event_sequence=RunRecord.event_sequence + 1, updated_at=func.now())
                .returning(RunRecord.event_sequence)
            )
            sequence = result.scalar_one()
            session.add(
                RunEventRecord(
                    run_id=run_id,
                    sequence=sequence,
                    event_type=event_type,
                    node_name=node_name,
                    payload=payload or {},
                )
            )
            return sequence

    async def start_attempt(self, run_id: str, node_name: str) -> str:
        async with self.sessions.begin() as session:
            await session.execute(
                select(RunRecord.id)
                .where(RunRecord.id == run_id)
                .with_for_update()
            )
            current = await session.scalar(
                select(func.max(NodeAttemptRecord.attempt_no)).where(
                    NodeAttemptRecord.run_id == run_id,
                    NodeAttemptRecord.node_name == node_name,
                )
            )
            attempt_no = int(current or 0) + 1
            attempt_id = f"{run_id}:{node_name}:{attempt_no}"
            session.add(
                NodeAttemptRecord(
                    id=attempt_id,
                    run_id=run_id,
                    node_name=node_name,
                    attempt_no=attempt_no,
                    status="running",
                )
            )
        await self.append_event(
            run_id,
            "node_started",
            node_name=node_name,
            payload={"attempt_id": attempt_id, "attempt_no": attempt_no},
        )
        return attempt_id

    async def finish_attempt(
        self,
        attempt_id: str,
        *,
        status: Literal["completed", "failed", "cancelled"],
        error_code: str | None = None,
    ) -> None:
        async with self.sessions.begin() as session:
            attempt = await session.get(NodeAttemptRecord, attempt_id)
            if attempt is None:
                raise PersistenceConflict("ATTEMPT_NOT_FOUND")
            if attempt.status != "running":
                if attempt.status == status and attempt.error_code == error_code:
                    return
                raise PersistenceConflict("ATTEMPT_ALREADY_TERMINAL")
            attempt.status = status
            attempt.error_code = error_code
            attempt.finished_at = datetime.now(timezone.utc)
            run_id = attempt.run_id
            node_name = attempt.node_name
        await self.append_event(
            run_id,
            f"node_{status}",
            node_name=node_name,
            payload={"attempt_id": attempt_id, "error_code": error_code},
        )

    async def reserve_model_call(
        self,
        *,
        run_id: str,
        node_name: str,
        idempotency_key: str,
        provider: str,
        model_name: str,
        request_payload: dict[str, Any],
        gateway_version: str | None = None,
        policy_decision_id: str | None = None,
        budget_entry_id: str | None = None,
    ) -> CallReservation:
        request_hash = canonical_hash(request_payload)
        async with self.sessions.begin() as session:
            existing = await session.scalar(
                select(ModelCallRecord)
                .where(ModelCallRecord.idempotency_key == idempotency_key)
                .with_for_update()
            )
            now = datetime.now(timezone.utc)
            if existing is not None:
                if existing.request_hash != request_hash:
                    raise PersistenceConflict("MODEL_CALL_KEY_PAYLOAD_MISMATCH")
                if existing.status == "completed":
                    return CallReservation(False, existing.id, existing.result_payload)
                if (
                    existing.status == "running"
                    and existing.lease_expires_at
                    and existing.lease_expires_at > now
                ):
                    raise OperationInProgress("MODEL_CALL_IN_PROGRESS")
                existing.status = "running"
                existing.error_code = None
                existing.lease_owner = self.worker_id
                existing.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
                return CallReservation(True, existing.id)
            call_id = uuid4().hex
            session.add(
                ModelCallRecord(
                    id=call_id,
                    run_id=run_id,
                    node_name=node_name,
                    idempotency_key=idempotency_key,
                    provider=provider,
                    model_name=model_name,
                    request_hash=request_hash,
                    status="running",
                    lease_owner=self.worker_id,
                    lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                    gateway_version=gateway_version,
                    policy_decision_id=policy_decision_id,
                    budget_entry_id=budget_entry_id,
                )
            )
            return CallReservation(True, call_id)

    async def complete_model_call(
        self, call_id: str, result_payload: dict[str, Any]
    ) -> None:
        await self._complete_call(ModelCallRecord, call_id, result_payload)

    async def fail_model_call(self, call_id: str, error_code: str) -> None:
        await self._fail_call(ModelCallRecord, call_id, error_code)

    async def reserve_tool_call(
        self,
        *,
        run_id: str,
        node_name: str,
        task_id: str,
        tool_name: str,
        idempotency_key: str,
        input_payload: dict[str, Any],
        gateway_version: str | None = None,
        policy_decision_id: str | None = None,
        budget_entry_id: str | None = None,
    ) -> CallReservation:
        input_hash = canonical_hash(input_payload)
        async with self.sessions.begin() as session:
            existing = await session.scalar(
                select(ToolCallRecord)
                .where(ToolCallRecord.idempotency_key == idempotency_key)
                .with_for_update()
            )
            now = datetime.now(timezone.utc)
            if existing is not None:
                if existing.input_hash != input_hash:
                    raise PersistenceConflict("TOOL_CALL_KEY_PAYLOAD_MISMATCH")
                if existing.status == "completed":
                    return CallReservation(False, existing.id, existing.result_payload)
                if (
                    existing.status == "running"
                    and existing.lease_expires_at
                    and existing.lease_expires_at > now
                ):
                    raise OperationInProgress("TOOL_CALL_IN_PROGRESS")
                existing.status = "running"
                existing.error_code = None
                existing.lease_owner = self.worker_id
                existing.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
                return CallReservation(True, existing.id)
            call_id = uuid4().hex
            session.add(
                ToolCallRecord(
                    id=call_id,
                    run_id=run_id,
                    node_name=node_name,
                    task_id=task_id,
                    tool_name=tool_name,
                    idempotency_key=idempotency_key,
                    input_hash=input_hash,
                    status="running",
                    lease_owner=self.worker_id,
                    lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                    gateway_version=gateway_version,
                    policy_decision_id=policy_decision_id,
                    budget_entry_id=budget_entry_id,
                )
            )
            return CallReservation(True, call_id)

    async def complete_tool_call(
        self, call_id: str, result_payload: dict[str, Any]
    ) -> None:
        await self._complete_call(ToolCallRecord, call_id, result_payload)

    async def fail_tool_call(self, call_id: str, error_code: str) -> None:
        await self._fail_call(ToolCallRecord, call_id, error_code)

    async def record_model_usage(
        self,
        call_id: str,
        *,
        attempt_count: int,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        usage_estimated: bool,
        cost_microunits: int | None,
    ) -> None:
        async with self.sessions.begin() as session:
            record = await session.get(
                ModelCallRecord, call_id, with_for_update=True
            )
            if record is None:
                raise PersistenceConflict("MODEL_CALL_NOT_FOUND")
            record.attempt_count = attempt_count
            record.input_tokens = input_tokens
            record.output_tokens = output_tokens
            record.total_tokens = total_tokens
            record.usage_estimated = usage_estimated
            record.cost_microunits = cost_microunits

    async def record_model_attempts(
        self, call_id: str, *, attempt_count: int
    ) -> None:
        async with self.sessions.begin() as session:
            record = await session.get(
                ModelCallRecord, call_id, with_for_update=True
            )
            if record is None:
                raise PersistenceConflict("MODEL_CALL_NOT_FOUND")
            record.attempt_count = attempt_count

    async def record_tool_attempts(
        self, call_id: str, *, attempt_count: int
    ) -> None:
        async with self.sessions.begin() as session:
            record = await session.get(
                ToolCallRecord, call_id, with_for_update=True
            )
            if record is None:
                raise PersistenceConflict("TOOL_CALL_NOT_FOUND")
            record.attempt_count = attempt_count

    async def _complete_call(self, model, call_id: str, payload: dict[str, Any]) -> None:
        async with self.sessions.begin() as session:
            record = await session.get(model, call_id, with_for_update=True)
            if record is None:
                raise PersistenceConflict("CALL_NOT_FOUND")
            if record.status == "completed":
                if record.result_payload != payload:
                    raise PersistenceConflict("CALL_COMPLETION_PAYLOAD_MISMATCH")
                return
            record.status = "completed"
            record.result_payload = payload
            record.error_code = None
            record.completed_at = datetime.now(timezone.utc)
            record.lease_owner = None
            record.lease_expires_at = None

    async def _fail_call(self, model, call_id: str, error_code: str) -> None:
        async with self.sessions.begin() as session:
            record = await session.get(model, call_id, with_for_update=True)
            if record is None:
                raise PersistenceConflict("CALL_NOT_FOUND")
            if record.status == "completed":
                raise PersistenceConflict("COMPLETED_CALL_CANNOT_FAIL")
            record.status = "failed"
            record.error_code = error_code[:128]
            record.completed_at = datetime.now(timezone.utc)
            record.lease_owner = None
            record.lease_expires_at = None

    async def update_checkpoint(self, run_id: str, checkpoint_id: str | None) -> None:
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(RunRecord)
                .where(RunRecord.id == run_id)
                .values(last_checkpoint_id=checkpoint_id, updated_at=func.now())
            )
            if result.rowcount != 1:
                raise PersistenceConflict("RUN_NOT_FOUND")

    async def write_terminal(
        self,
        run_id: str,
        status: str,
        result_payload: dict[str, Any],
    ) -> bool:
        async with self.sessions.begin() as session:
            inserted = await session.scalar(
                pg_insert(TerminalResultRecord)
                .values(
                    run_id=run_id,
                    status=status,
                    result_payload=result_payload,
                )
                .on_conflict_do_nothing(index_elements=["run_id"])
                .returning(TerminalResultRecord.run_id)
            )
            if inserted is None:
                existing = await session.get(TerminalResultRecord, run_id)
                if existing is None:
                    raise PersistenceConflict("TERMINAL_RESULT_WRITE_LOST")
                if existing.status == status and existing.result_payload == result_payload:
                    return False
                raise PersistenceConflict("TERMINAL_RESULT_CONFLICT")
            await session.execute(
                update(RunRecord)
                .where(RunRecord.id == run_id)
                .values(status=status, updated_at=func.now(), version=RunRecord.version + 1)
            )
        await self.append_event(run_id, "run_terminal", payload={"status": status})
        return True

    async def get_terminal(self, run_id: str) -> TerminalResultRecord | None:
        async with self.sessions() as session:
            return await session.get(TerminalResultRecord, run_id)

    async def add_artifact(
        self,
        run_id: str,
        artifact_type: str,
        uri: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        async with self.sessions.begin() as session:
            existing = await session.scalar(
                select(ArtifactRefRecord).where(
                    ArtifactRefRecord.run_id == run_id,
                    ArtifactRefRecord.artifact_type == artifact_type,
                    ArtifactRefRecord.uri == uri,
                )
            )
            if existing:
                return existing.id
            artifact_id = uuid4().hex
            session.add(
                ArtifactRefRecord(
                    id=artifact_id,
                    run_id=run_id,
                    artifact_type=artifact_type,
                    uri=uri,
                    metadata_json=metadata or {},
                )
            )
            return artifact_id
