from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from financial_research_agent.domain.models import QuerySpec
from financial_research_agent.memory.models import (
    CandidateMemory,
    MemoryKind,
    MemoryRecord,
    MemoryVersion,
    MemoryScope,
    MemorySource,
    MemoryStatus,
)
from financial_research_agent.persistence.models import (
    MemoryAuditRecord,
    MemoryRecordModel,
    MemoryVersionRecord,
)


PREFERENCE_SESSION_KEY = "preference"
EPISODIC_SESSION_KEY = "episodic"
SESSION_KEYS = {
    "last_stock_codes",
    "last_start_date",
    "last_end_date",
    "last_report_candidates",
}
PREFERENCE_KEYS = {"report_language", "output_length", "risk_focus"}
SENSITIVE_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~-]{12,}"),
    re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(api[_ -]?key|password|secret)\s*[:=]\s*\S+"),
)


class MemoryRejected(ValueError):
    pass


class MemoryConflict(RuntimeError):
    pass


class MemoryNotFound(LookupError):
    pass


class MemoryManager:
    def __init__(
        self,
        sessions: async_sessionmaker,
        *,
        session_ttl_seconds: int = 30 * 24 * 60 * 60,
        preference_ttl_seconds: int | None = None,
        episodic_ttl_seconds: int = 180 * 24 * 60 * 60,
    ) -> None:
        self.sessions = sessions
        self.session_ttl_seconds = session_ttl_seconds
        self.preference_ttl_seconds = preference_ttl_seconds
        self.episodic_ttl_seconds = episodic_ttl_seconds

    async def write(
        self,
        scope: MemoryScope,
        candidate: CandidateMemory,
        *,
        expected_version: int | None = None,
    ) -> MemoryRecord:
        try:
            self._validate_candidate(candidate)
        except Exception as exc:
            await self._audit(
                scope,
                action="reject",
                reason_code=str(exc)[:128],
                metadata={"kind": candidate.kind.value, "key": candidate.key},
            )
            raise
        session_key = self._session_key(scope, candidate.kind)
        now = datetime.now(timezone.utc)
        ttl = candidate.ttl_seconds
        if ttl is None:
            ttl = {
                MemoryKind.SESSION: self.session_ttl_seconds,
                MemoryKind.PREFERENCE: self.preference_ttl_seconds,
                MemoryKind.EPISODIC: self.episodic_ttl_seconds,
            }[candidate.kind]
        expires_at = now + timedelta(seconds=ttl) if ttl else None
        action = "create"
        write_version = True
        reason_code = "MEMORY_WRITE_ALLOWED"
        async with self.sessions.begin() as session:
            record = await session.scalar(
                select(MemoryRecordModel)
                .where(
                    MemoryRecordModel.tenant_id == scope.tenant_id,
                    MemoryRecordModel.user_id == scope.user_id,
                    MemoryRecordModel.session_key == session_key,
                    MemoryRecordModel.kind == candidate.kind.value,
                    MemoryRecordModel.memory_key == candidate.key,
                )
                .with_for_update()
            )
            if record is None:
                record = MemoryRecordModel(
                    id=uuid4().hex,
                    tenant_id=scope.tenant_id,
                    user_id=scope.user_id,
                    session_key=session_key,
                    kind=candidate.kind.value,
                    memory_key=candidate.key,
                    value=candidate.value,
                    version=1,
                    status=MemoryStatus.ACTIVE.value,
                    source_type=candidate.source.source_type,
                    source_id=candidate.source.source_id,
                    source_run_id=candidate.source.run_id,
                    source_metadata=candidate.source.metadata,
                    explicitly_confirmed=candidate.explicitly_confirmed,
                    expires_at=expires_at,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
            else:
                if (
                    expected_version is not None
                    and record.version != expected_version
                ):
                    raise MemoryConflict(
                        f"MEMORY_VERSION_CONFLICT:expected={expected_version}:actual={record.version}"
                    )
                action = "update"
                if (
                    record.status == MemoryStatus.ACTIVE.value
                    and record.value == candidate.value
                    and record.source_type == candidate.source.source_type
                    and record.source_id == candidate.source.source_id
                    and record.source_run_id == candidate.source.run_id
                    and (record.source_metadata or {}) == candidate.source.metadata
                ):
                    write_version = False
                    reason_code = "MEMORY_WRITE_IDEMPOTENT"
                else:
                    record.value = candidate.value
                    record.version += 1
                    record.status = MemoryStatus.ACTIVE.value
                    record.source_type = candidate.source.source_type
                    record.source_id = candidate.source.source_id
                    record.source_run_id = candidate.source.run_id
                    record.source_metadata = candidate.source.metadata
                    record.explicitly_confirmed = candidate.explicitly_confirmed
                    record.expires_at = expires_at
                    record.deleted_at = None
                    record.updated_at = now
            if write_version:
                session.add(self._version_record(record, now=now))
            session.add(
                self._audit_record(
                    scope,
                    action=action,
                    reason_code=reason_code,
                    memory_id=record.id,
                    metadata={
                        "kind": candidate.kind.value,
                        "key": candidate.key,
                        "version": record.version,
                    },
                )
            )
        return self._to_model(record)

    async def list(
        self,
        scope: MemoryScope,
        *,
        kind: MemoryKind | None = None,
        audit_read: bool = True,
    ) -> list[MemoryRecord]:
        await self.expire_due(scope=scope)
        clauses = [
            MemoryRecordModel.tenant_id == scope.tenant_id,
            MemoryRecordModel.user_id == scope.user_id,
            MemoryRecordModel.status == MemoryStatus.ACTIVE.value,
        ]
        if kind == MemoryKind.SESSION:
            clauses.extend(
                [
                    MemoryRecordModel.kind == MemoryKind.SESSION.value,
                    MemoryRecordModel.session_key == scope.session_id,
                ]
            )
        elif kind == MemoryKind.PREFERENCE:
            clauses.extend(
                [
                    MemoryRecordModel.kind == MemoryKind.PREFERENCE.value,
                    MemoryRecordModel.session_key == PREFERENCE_SESSION_KEY,
                ]
            )
        elif kind == MemoryKind.EPISODIC:
            clauses.extend(
                [
                    MemoryRecordModel.kind == MemoryKind.EPISODIC.value,
                    MemoryRecordModel.session_key == EPISODIC_SESSION_KEY,
                ]
            )
        else:
            clauses.append(
                (
                    (
                        MemoryRecordModel.kind == MemoryKind.SESSION.value
                    )
                    & (
                        MemoryRecordModel.session_key == scope.session_id
                    )
                )
                | (
                    (
                        MemoryRecordModel.kind
                        == MemoryKind.PREFERENCE.value
                    )
                    & (
                        MemoryRecordModel.session_key
                        == PREFERENCE_SESSION_KEY
                    )
                )
                | (
                    (MemoryRecordModel.kind == MemoryKind.EPISODIC.value)
                    & (MemoryRecordModel.session_key == EPISODIC_SESSION_KEY)
                )
            )
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(MemoryRecordModel)
                    .where(*clauses)
                    .order_by(
                        MemoryRecordModel.kind,
                        MemoryRecordModel.memory_key,
                    )
                )
            ).all()
        if audit_read:
            await self._audit(
                scope,
                action="read",
                reason_code="MEMORY_SCOPE_READ",
                metadata={
                    "kind": kind.value if kind else "all",
                    "count": len(rows),
                },
            )
        return [self._to_model(item) for item in rows]

    async def delete(
        self,
        scope: MemoryScope,
        memory_id: str,
        *,
        expected_version: int | None = None,
    ) -> MemoryRecord:
        now = datetime.now(timezone.utc)
        async with self.sessions.begin() as session:
            record = await session.get(
                MemoryRecordModel, memory_id, with_for_update=True
            )
            if record is None or not self._matches_scope(record, scope):
                raise MemoryNotFound("MEMORY_NOT_FOUND")
            if (
                expected_version is not None
                and record.version != expected_version
            ):
                raise MemoryConflict(
                    f"MEMORY_VERSION_CONFLICT:expected={expected_version}:actual={record.version}"
                )
            if record.status == MemoryStatus.ACTIVE.value:
                record.status = MemoryStatus.DELETED.value
                record.version += 1
                record.deleted_at = now
                record.updated_at = now
                session.add(self._version_record(record, now=now))
            session.add(
                self._audit_record(
                    scope,
                    action="delete",
                    reason_code="USER_DELETE",
                    memory_id=record.id,
                    metadata={"version": record.version},
                )
            )
        return self._to_model(record)

    async def expire_due(self, *, scope: MemoryScope | None = None) -> int:
        now = datetime.now(timezone.utc)
        clauses = [
            MemoryRecordModel.status == MemoryStatus.ACTIVE.value,
            MemoryRecordModel.expires_at.is_not(None),
            MemoryRecordModel.expires_at <= now,
        ]
        if scope is not None:
            clauses.extend(
                [
                    MemoryRecordModel.tenant_id == scope.tenant_id,
                    MemoryRecordModel.user_id == scope.user_id,
                ]
            )
        count = 0
        async with self.sessions.begin() as session:
            rows = (
                await session.scalars(
                    select(MemoryRecordModel)
                    .where(*clauses)
                    .with_for_update()
                )
            ).all()
            for record in rows:
                record.status = MemoryStatus.EXPIRED.value
                record.version += 1
                record.updated_at = now
                session.add(self._version_record(record, now=now))
                count += 1
                audit_scope = MemoryScope(
                    tenant_id=record.tenant_id,
                    user_id=record.user_id,
                    session_id=(
                        record.session_key
                        if record.kind == MemoryKind.SESSION.value
                        else "default"
                    ),
                )
                session.add(
                    self._audit_record(
                        audit_scope,
                        action="expire",
                        reason_code="TTL_EXPIRED",
                        memory_id=record.id,
                        metadata={"version": record.version},
                    )
                )
        return count

    async def remember_query(
        self,
        scope: MemoryScope,
        query: QuerySpec,
        *,
        run_id: str,
    ) -> list[MemoryRecord]:
        source = MemorySource(
            source_type="query_spec",
            source_id=run_id,
            run_id=run_id,
        )
        candidates = [
            CandidateMemory(
                kind=MemoryKind.SESSION,
                key="last_stock_codes",
                value=query.stock_codes,
                source=source,
            )
        ]
        if query.start_date:
            candidates.append(
                CandidateMemory(
                    kind=MemoryKind.SESSION,
                    key="last_start_date",
                    value=query.start_date.isoformat(),
                    source=source,
                )
            )
        if query.end_date:
            candidates.append(
                CandidateMemory(
                    kind=MemoryKind.SESSION,
                    key="last_end_date",
                    value=query.end_date.isoformat(),
                    source=source,
                )
            )
        return [await self.write(scope, item) for item in candidates]

    async def read(
        self,
        scope: MemoryScope,
        *,
        kind: MemoryKind | None = None,
    ) -> list[MemoryRecord]:
        return await self.list(scope, kind=kind)

    async def remember_report_candidates(
        self,
        scope: MemoryScope,
        candidates: list[dict[str, Any]],
        *,
        run_id: str,
    ) -> MemoryRecord:
        compact = [
            {
                key: item.get(key)
                for key in (
                    "candidate_id",
                    "document_id",
                    "stock_code",
                    "institution",
                    "report_title",
                    "report_date",
                    "rank",
                    "candidate_set_id",
                )
            }
            for item in candidates[:5]
        ]
        return await self.write(
            scope,
            CandidateMemory(
                kind=MemoryKind.SESSION,
                key="last_report_candidates",
                value=compact,
                source=MemorySource(
                    source_type="query_spec",
                    source_id=run_id,
                    run_id=run_id,
                ),
                ttl_seconds=21_600,
            ),
        )

    async def update(
        self,
        scope: MemoryScope,
        candidate: CandidateMemory,
        *,
        expected_version: int,
    ) -> MemoryRecord:
        return await self.write(
            scope,
            candidate,
            expected_version=expected_version,
        )

    async def forget(
        self,
        scope: MemoryScope,
        memory_id: str,
        *,
        expected_version: int | None = None,
    ) -> MemoryRecord:
        return await self.delete(
            scope,
            memory_id,
            expected_version=expected_version,
        )

    async def reflect(
        self,
        scope: MemoryScope,
        *,
        run_id: str,
        task_type: str,
        payload: dict[str, Any],
        validation_passed: bool,
        skill_versions: list[str] | None = None,
        model_version: str | None = None,
    ) -> MemoryRecord:
        if not validation_passed:
            await self._audit(
                scope,
                action="reject",
                reason_code="EPISODIC_RUN_NOT_VALIDATED",
                metadata={"run_id": run_id, "task_type": task_type},
            )
            raise MemoryRejected("EPISODIC_RUN_NOT_VALIDATED")
        key_suffix = re.sub(r"[^a-z0-9]", "", run_id.lower())[:40]
        candidate = CandidateMemory(
            kind=MemoryKind.EPISODIC,
            key=f"episode_{key_suffix}",
            value={
                "task_type": task_type,
                "result": payload,
                "skill_versions": skill_versions or [],
                "model_version": model_version,
                "historical_only": True,
            },
            source=MemorySource(
                source_type="validated_run",
                source_id=run_id,
                run_id=run_id,
                metadata={"validation_passed": True},
            ),
            validation_passed=True,
        )
        record = await self.write(scope, candidate)
        await self._audit(
            scope,
            action="reflect",
            reason_code="VALIDATED_RUN_REFLECTED",
            memory_id=record.memory_id,
            metadata={"run_id": run_id, "version": record.version},
        )
        return record

    async def versions(
        self, scope: MemoryScope, memory_id: str
    ) -> list[MemoryVersion]:
        async with self.sessions() as session:
            record = await session.get(MemoryRecordModel, memory_id)
            if record is None or not self._matches_scope(record, scope):
                raise MemoryNotFound("MEMORY_NOT_FOUND")
            rows = (
                await session.scalars(
                    select(MemoryVersionRecord)
                    .where(MemoryVersionRecord.memory_id == memory_id)
                    .order_by(MemoryVersionRecord.version)
                )
            ).all()
        return [
            MemoryVersion(
                memory_id=item.memory_id,
                version=item.version,
                status=MemoryStatus(item.status),
                value=item.value,
                source=MemorySource(
                    source_type=item.source_type,
                    source_id=item.source_id,
                    run_id=item.source_run_id,
                    metadata=item.source_metadata or {},
                ),
                created_at=item.created_at,
            )
            for item in rows
        ]

    @staticmethod
    def resolve_question(
        question: str, memory: list[MemoryRecord]
    ) -> tuple[str, list[str]]:
        if re.search(r"\b\d{6}\b", question):
            return question, []
        ordinal_match = re.search(
            r"第\s*([1-5一二三四五])\s*(?:份|篇|个)(?:研报|报告)?",
            question,
        )
        if ordinal_match:
            raw = ordinal_match.group(1)
            ordinal = int(raw) if raw.isdigit() else {
                "一": 1, "二": 2, "三": 3, "四": 4, "五": 5
            }[raw]
            record = next(
                (item for item in memory if item.key == "last_report_candidates"),
                None,
            )
            candidates = record.value if record is not None else None
            if isinstance(candidates, list) and len(candidates) >= ordinal:
                selected = candidates[ordinal - 1]
                code = str(selected.get("stock_code") or "")
                candidate_id = str(selected.get("candidate_id") or "")
                title = str(selected.get("report_title") or "")
                if re.fullmatch(r"\d{6}", code) and re.fullmatch(
                    r"rpt_[a-f0-9]{16}", candidate_id
                ):
                    return (
                        f"{question}（本会话候选ID：{candidate_id}；"
                        f"标的代码：{code}；标题：{title}）",
                        [f"SESSION_REPORT_REFERENCE_RESOLVED:{record.memory_id}"],
                    )
        if not any(token in question for token in ("它", "该公司", "这个标的", "继续")):
            return question, []
        record = next(
            (item for item in memory if item.key == "last_stock_codes"), None
        )
        codes = record.value if record is not None else None
        if not isinstance(codes, list) or not codes:
            return question, []
        code = str(codes[0])
        if not re.fullmatch(r"\d{6}", code):
            return question, []
        return f"{question}（本会话已确认标的代码：{code}）", [
            f"SESSION_REFERENCE_RESOLVED:{record.memory_id}"
        ]

    def _validate_candidate(self, candidate: CandidateMemory) -> None:
        allowed = {
            MemoryKind.SESSION: candidate.key in SESSION_KEYS,
            MemoryKind.PREFERENCE: candidate.key in PREFERENCE_KEYS,
            MemoryKind.EPISODIC: candidate.key.startswith(("episode_", "failure_")),
        }[candidate.kind]
        if not allowed:
            raise MemoryRejected("MEMORY_KEY_NOT_ALLOWED")
        if candidate.kind == MemoryKind.PREFERENCE and not (
            candidate.explicitly_confirmed
            and candidate.source.source_type
            in {"explicit_user_confirmation", "api"}
        ):
            raise MemoryRejected("PREFERENCE_CONFIRMATION_REQUIRED")
        if candidate.kind == MemoryKind.EPISODIC and not (
            candidate.validation_passed
            and candidate.source.source_type in {"validated_run", "reflection"}
            and candidate.source.metadata.get("validation_passed") is True
        ):
            raise MemoryRejected("EPISODIC_VALIDATION_REQUIRED")
        if self._contains_sensitive(candidate.value):
            raise MemoryRejected("MEMORY_SENSITIVE_CONTENT_REJECTED")
        self._validate_value(candidate)

    @staticmethod
    def _validate_value(candidate: CandidateMemory) -> None:
        value = candidate.value
        if candidate.key == "last_stock_codes":
            if not (
                isinstance(value, list)
                and 1 <= len(value) <= 5
                and all(
                    isinstance(item, str)
                    and re.fullmatch(r"\d{6}", item)
                    for item in value
                )
            ):
                raise MemoryRejected("MEMORY_STOCK_CODES_INVALID")
        elif candidate.key in {"last_start_date", "last_end_date"}:
            if not (
                isinstance(value, str)
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
            ):
                raise MemoryRejected("MEMORY_DATE_INVALID")
        elif candidate.key == "last_report_candidates":
            if not (
                isinstance(value, list)
                and 1 <= len(value) <= 5
                and all(
                    isinstance(item, dict)
                    and re.fullmatch(r"rpt_[a-f0-9]{16}", str(item.get("candidate_id", "")))
                    and re.fullmatch(r"\d{6}", str(item.get("stock_code", "")))
                    for item in value
                )
            ):
                raise MemoryRejected("MEMORY_REPORT_CANDIDATES_INVALID")
        elif candidate.key == "report_language" and value not in {
            "zh-CN",
            "en-US",
        }:
            raise MemoryRejected("MEMORY_LANGUAGE_INVALID")
        elif candidate.key == "output_length" and value not in {
            "concise",
            "standard",
            "detailed",
        }:
            raise MemoryRejected("MEMORY_OUTPUT_LENGTH_INVALID")
        elif candidate.key == "risk_focus" and not isinstance(value, bool):
            raise MemoryRejected("MEMORY_RISK_FOCUS_INVALID")

    @staticmethod
    def _contains_sensitive(value: Any) -> bool:
        if isinstance(value, dict):
            return any(
                MemoryManager._contains_sensitive(key)
                or MemoryManager._contains_sensitive(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(MemoryManager._contains_sensitive(item) for item in value)
        if not isinstance(value, str):
            return False
        return any(pattern.search(value) for pattern in SENSITIVE_PATTERNS)

    @staticmethod
    def _session_key(scope: MemoryScope, kind: MemoryKind) -> str:
        return {
            MemoryKind.SESSION: scope.session_id,
            MemoryKind.PREFERENCE: PREFERENCE_SESSION_KEY,
            MemoryKind.EPISODIC: EPISODIC_SESSION_KEY,
        }[kind]

    @staticmethod
    def _matches_scope(
        record: MemoryRecordModel, scope: MemoryScope
    ) -> bool:
        return (
            record.tenant_id == scope.tenant_id
            and record.user_id == scope.user_id
            and (
                (
                    record.kind == MemoryKind.SESSION.value
                    and record.session_key == scope.session_id
                )
                or (
                    record.kind == MemoryKind.PREFERENCE.value
                    and record.session_key == PREFERENCE_SESSION_KEY
                )
                or (
                    record.kind == MemoryKind.EPISODIC.value
                    and record.session_key == EPISODIC_SESSION_KEY
                )
            )
        )

    @staticmethod
    def _to_model(record: MemoryRecordModel) -> MemoryRecord:
        return MemoryRecord(
            memory_id=record.id,
            scope=MemoryScope(
                tenant_id=record.tenant_id,
                user_id=record.user_id,
                session_id=(
                    record.session_key
                    if record.kind == MemoryKind.SESSION.value
                    else "default"
                ),
            ),
            kind=record.kind,
            key=record.memory_key,
            value=record.value,
            version=record.version,
            status=record.status,
            source=MemorySource(
                source_type=record.source_type,
                source_id=record.source_id,
                run_id=record.source_run_id,
                metadata=record.source_metadata or {},
            ),
            expires_at=record.expires_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
            deleted_at=record.deleted_at,
        )

    @staticmethod
    def _version_record(
        record: MemoryRecordModel, *, now: datetime
    ) -> MemoryVersionRecord:
        return MemoryVersionRecord(
            id=uuid4().hex,
            memory_id=record.id,
            version=record.version,
            status=record.status,
            value=record.value,
            source_type=record.source_type,
            source_id=record.source_id,
            source_run_id=record.source_run_id,
            source_metadata=record.source_metadata or {},
            created_at=now,
        )

    async def _audit(
        self,
        scope: MemoryScope,
        *,
        action: str,
        reason_code: str,
        memory_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        async with self.sessions.begin() as session:
            session.add(
                self._audit_record(
                    scope,
                    action=action,
                    reason_code=reason_code,
                    memory_id=memory_id,
                    metadata=metadata,
                )
            )

    @staticmethod
    def _audit_record(
        scope: MemoryScope,
        *,
        action: str,
        reason_code: str,
        memory_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryAuditRecord:
        return MemoryAuditRecord(
            id=uuid4().hex,
            memory_id=memory_id,
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            session_key=scope.session_id,
            action=action,
            reason_code=reason_code,
            metadata_json=metadata or {},
        )
