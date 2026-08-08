from __future__ import annotations

from datetime import date, datetime, time as datetime_time, timedelta, timezone
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from financial_research_agent.knowledge.models import KnowledgeEvent, KnowledgeEventStatus
from financial_research_agent.persistence.models import (
    KnowledgeEventRecord,
    KnowledgeEventTransitionRecord,
    KnowledgeSourceCursorRecord,
)


class KnowledgeStore:
    def __init__(self, sessions: async_sessionmaker) -> None:
        self.sessions = sessions

    async def cursor(self, source_id: str) -> str | None:
        async with self.sessions() as session:
            record = await session.get(KnowledgeSourceCursorRecord, source_id)
            return record.cursor_value if record else None

    async def save_cursor(
        self,
        *,
        source_id: str,
        cursor: str | None,
        high_watermark: datetime | None,
        source_rank: int,
        license_name: str,
        metadata: dict | None = None,
    ) -> None:
        values = {
            "source_id": source_id,
            "cursor_value": cursor,
            "high_watermark": high_watermark,
            "source_rank": source_rank,
            "license_name": license_name,
            "metadata_json": metadata or {},
            "updated_at": datetime.now(timezone.utc),
        }
        async with self.sessions.begin() as session:
            await session.execute(
                pg_insert(KnowledgeSourceCursorRecord)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[KnowledgeSourceCursorRecord.source_id],
                    set_={
                        getattr(KnowledgeSourceCursorRecord, key): value
                        for key, value in values.items()
                        if key != "source_id"
                    },
                )
            )

    async def create_candidate(self, event: KnowledgeEvent) -> tuple[KnowledgeEvent, bool]:
        values = self._values(event)
        async with self.sessions.begin() as session:
            inserted = await session.scalar(
                pg_insert(KnowledgeEventRecord)
                .values(**values)
                .on_conflict_do_nothing(constraint="uq_knowledge_event_source_version")
                .returning(KnowledgeEventRecord.id)
            )
            if inserted is not None:
                session.add(
                    self._transition_record(
                        event.event_id,
                        None,
                        KnowledgeEventStatus.CANDIDATE,
                        "SOURCE_RECORD_ACCEPTED",
                    )
                )
                return event, True
            existing = await session.scalar(
                select(KnowledgeEventRecord).where(
                    KnowledgeEventRecord.source_id == event.source_id,
                    KnowledgeEventRecord.source_record_id == event.source_record_id,
                    KnowledgeEventRecord.raw_version == event.raw_version,
                )
            )
            if existing is None:
                raise RuntimeError("KNOWLEDGE_EVENT_WRITE_LOST")
            return self._to_model(existing), False

    async def find_active_by_canonical(
        self, canonical_key: str, *, exclude_event_id: str | None = None
    ) -> list[KnowledgeEvent]:
        clauses = [
            KnowledgeEventRecord.canonical_key == canonical_key,
            KnowledgeEventRecord.status == KnowledgeEventStatus.ACTIVE.value,
        ]
        if exclude_event_id:
            clauses.append(KnowledgeEventRecord.id != exclude_event_id)
        async with self.sessions() as session:
            rows = (
                await session.scalars(select(KnowledgeEventRecord).where(*clauses))
            ).all()
        return [self._to_model(item) for item in rows]

    async def transition(
        self,
        event_id: str,
        to_status: KnowledgeEventStatus,
        *,
        reason_code: str,
        rejection_reason: str | None = None,
        conflict_group: str | None = None,
        metadata: dict | None = None,
    ) -> KnowledgeEvent:
        allowed = {
            KnowledgeEventStatus.CANDIDATE: {
                KnowledgeEventStatus.ACTIVE,
                KnowledgeEventStatus.REJECTED,
            },
            KnowledgeEventStatus.ACTIVE: {KnowledgeEventStatus.SUPERSEDED},
        }
        async with self.sessions.begin() as session:
            record = await session.get(KnowledgeEventRecord, event_id, with_for_update=True)
            if record is None:
                raise LookupError("KNOWLEDGE_EVENT_NOT_FOUND")
            current = KnowledgeEventStatus(record.status)
            if current == to_status:
                return self._to_model(record)
            if to_status not in allowed.get(current, set()):
                raise RuntimeError(
                    f"KNOWLEDGE_STATUS_TRANSITION_DENIED:{current.value}:{to_status.value}"
                )
            record.status = to_status.value
            record.rejection_reason = rejection_reason
            record.conflict_group = conflict_group or record.conflict_group
            record.updated_at = datetime.now(timezone.utc)
            session.add(
                self._transition_record(
                    event_id,
                    current,
                    to_status,
                    reason_code,
                    metadata=metadata,
                )
            )
        return self._to_model(record)

    async def mark_conflict(self, event_id: str, conflict_group: str) -> None:
        async with self.sessions.begin() as session:
            record = await session.get(KnowledgeEventRecord, event_id, with_for_update=True)
            if record is None:
                raise LookupError("KNOWLEDGE_EVENT_NOT_FOUND")
            record.conflict_group = conflict_group
            record.updated_at = datetime.now(timezone.utc)

    async def search_active(
        self,
        *,
        symbol: str,
        query: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 20,
    ) -> list[KnowledgeEvent]:
        clauses = [
            KnowledgeEventRecord.status == KnowledgeEventStatus.ACTIVE.value,
            KnowledgeEventRecord.symbol == symbol,
        ]
        if query:
            pattern = f"%{query.strip()}%"
            clauses.append(
                or_(
                    KnowledgeEventRecord.title.ilike(pattern),
                    KnowledgeEventRecord.content.ilike(pattern),
                )
            )
        if start_date:
            clauses.append(KnowledgeEventRecord.published_at >= start_date)
        if end_date:
            end_exclusive = datetime.combine(
                end_date + timedelta(days=1),
                datetime_time.min,
                tzinfo=timezone.utc,
            )
            clauses.append(KnowledgeEventRecord.published_at < end_exclusive)
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(KnowledgeEventRecord)
                    .where(*clauses)
                    .order_by(
                        KnowledgeEventRecord.published_at.desc(),
                        KnowledgeEventRecord.source_rank.asc(),
                    )
                    .limit(limit)
                )
            ).all()
        return [self._to_model(item) for item in rows]

    @staticmethod
    def _transition_record(
        event_id: str,
        from_status: KnowledgeEventStatus | None,
        to_status: KnowledgeEventStatus,
        reason_code: str,
        *,
        metadata: dict | None = None,
    ) -> KnowledgeEventTransitionRecord:
        return KnowledgeEventTransitionRecord(
            id=uuid4().hex,
            event_id=event_id,
            from_status=from_status.value if from_status else None,
            to_status=to_status.value,
            reason_code=reason_code,
            metadata_json=metadata or {},
        )

    @staticmethod
    def _values(event: KnowledgeEvent) -> dict:
        payload = event.model_dump(mode="python")
        payload["id"] = payload.pop("event_id")
        payload["status"] = event.status.value
        payload["metadata_json"] = payload.pop("metadata")
        return payload

    @staticmethod
    def _to_model(record: KnowledgeEventRecord) -> KnowledgeEvent:
        return KnowledgeEvent(
            event_id=record.id,
            canonical_key=record.canonical_key,
            symbol=record.symbol,
            event_type=record.event_type,
            title=record.title,
            content=record.content,
            event_time=record.event_time,
            published_at=record.published_at,
            ingested_at=record.ingested_at,
            available_at=record.available_at,
            source_id=record.source_id,
            source_record_id=record.source_record_id,
            source_url=record.source_url,
            source_rank=record.source_rank,
            content_hash=record.content_hash,
            raw_version=record.raw_version,
            extraction_version=record.extraction_version,
            status=KnowledgeEventStatus(record.status),
            raw_locator=record.raw_locator,
            evidence_refs=record.evidence_refs,
            entity_evidence=record.entity_evidence,
            supersedes=record.supersedes,
            conflict_group=record.conflict_group,
            rejection_reason=record.rejection_reason,
            metadata=record.metadata_json,
        )
