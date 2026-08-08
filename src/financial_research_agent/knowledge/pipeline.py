from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

from financial_research_agent.knowledge.lake import KnowledgeLake
from financial_research_agent.knowledge.models import (
    KnowledgeEvent,
    KnowledgeEventStatus,
    KnowledgeIngestionResult,
    RawKnowledgeItem,
    SourceBatch,
)
from financial_research_agent.knowledge.source import KnowledgeSource
from financial_research_agent.knowledge.store import KnowledgeStore


EXTRACTION_VERSION = "event_extraction_v1"


class KnowledgePipeline:
    def __init__(
        self,
        *,
        source: KnowledgeSource,
        lake: KnowledgeLake,
        store: KnowledgeStore,
        allowed_symbols: set[str],
    ) -> None:
        self.source = source
        self.lake = lake
        self.store = store
        self.allowed_symbols = allowed_symbols

    async def run_once(self, *, limit: int = 100) -> KnowledgeIngestionResult:
        cursor_before = await self.store.cursor(self.source.source_id)
        batch = await self.source.fetch(cursor_before, limit)
        if batch.source_id != self.source.source_id:
            raise ValueError("KNOWLEDGE_SOURCE_ID_MISMATCH")
        raw_locator, snapshot_id = self.lake.append(batch)
        result = KnowledgeIngestionResult(
            source_id=batch.source_id,
            cursor_before=cursor_before,
            cursor_after=batch.cursor_after,
            raw_rows=len(batch.records),
            snapshot_id=snapshot_id,
        )
        for item in batch.records:
            event = self._candidate(batch, item, raw_locator)
            _, created = await self.store.create_candidate(event)
            if not created:
                result.duplicates += 1
                continue
            result.candidates += 1
            rejection = self._validate(item, batch.fetched_at)
            if rejection:
                await self.store.transition(
                    event.event_id,
                    KnowledgeEventStatus.REJECTED,
                    reason_code=rejection,
                    rejection_reason=rejection,
                )
                result.rejected += 1
                continue
            existing = await self.store.find_active_by_canonical(
                event.canonical_key, exclude_event_id=event.event_id
            )
            conflicting = [
                other for other in existing if other.content_hash != event.content_hash
            ]
            conflict_group = event.canonical_key if conflicting else None
            for other in conflicting:
                await self.store.mark_conflict(other.event_id, event.canonical_key)
            await self.store.transition(
                event.event_id,
                KnowledgeEventStatus.ACTIVE,
                reason_code=(
                    "SOURCE_TIME_ENTITY_VALID_WITH_CONFLICT"
                    if conflicting
                    else "SOURCE_TIME_ENTITY_VALID"
                ),
                conflict_group=conflict_group,
                metadata={"conflicting_event_ids": [other.event_id for other in conflicting]},
            )
            result.active += 1
            result.conflicts += len(conflicting)
            if item.supersedes:
                try:
                    await self.store.transition(
                        item.supersedes,
                        KnowledgeEventStatus.SUPERSEDED,
                        reason_code="SOURCE_DECLARED_SUPERSESSION",
                        metadata={"superseded_by": event.event_id},
                    )
                except (LookupError, RuntimeError) as exc:
                    result.warnings.append(
                        f"SUPERSESSION_NOT_APPLIED:{item.supersedes}:{type(exc).__name__}"
                    )
        high_watermark = max((item.published_at for item in batch.records), default=None)
        await self.store.save_cursor(
            source_id=batch.source_id,
            cursor=batch.cursor_after,
            high_watermark=high_watermark,
            source_rank=batch.source_rank,
            license_name=batch.license_name,
            metadata={"snapshot_id": snapshot_id, "raw_rows": len(batch.records)},
        )
        return result

    @staticmethod
    def _candidate(
        batch: SourceBatch, item: RawKnowledgeItem, raw_locator: str
    ) -> KnowledgeEvent:
        ingested_at = datetime.now(timezone.utc)
        normalized_title = re.sub(r"\W+", "", item.title).lower()
        canonical_input = (
            f"{item.symbol}|{item.event_type}|{item.event_time.date().isoformat()}|"
            f"{normalized_title}"
        )
        canonical_key = hashlib.sha256(canonical_input.encode()).hexdigest()
        content_hash = hashlib.sha256(item.content.strip().encode()).hexdigest()
        event_input = f"{batch.source_id}|{item.source_record_id}|{item.raw_version}"
        event_id = hashlib.sha256(event_input.encode()).hexdigest()[:32]
        separator = "&" if "?" in raw_locator else "?"
        locator = (
            f"{raw_locator}{separator}source_id={batch.source_id}"
            f"&source_record_id={item.source_record_id}&raw_version={item.raw_version}"
        )
        return KnowledgeEvent(
            event_id=event_id,
            canonical_key=canonical_key,
            symbol=item.symbol,
            event_type=item.event_type,
            title=item.title,
            content=item.content,
            event_time=item.event_time,
            published_at=item.published_at,
            ingested_at=ingested_at,
            available_at=item.available_at or item.published_at,
            source_id=batch.source_id,
            source_record_id=item.source_record_id,
            source_url=item.source_url,
            source_rank=batch.source_rank,
            content_hash=content_hash,
            raw_version=item.raw_version,
            extraction_version=EXTRACTION_VERSION,
            status=KnowledgeEventStatus.CANDIDATE,
            raw_locator=locator,
            evidence_refs=[item.source_url, locator],
            entity_evidence=item.entity_evidence,
            supersedes=item.supersedes,
            metadata={
                **item.metadata,
                "license_name": batch.license_name,
                "source_fetched_at": batch.fetched_at.isoformat(),
            },
        )

    def _validate(self, item: RawKnowledgeItem, fetched_at: datetime) -> str | None:
        if item.symbol not in self.allowed_symbols:
            return "SYMBOL_NOT_ALLOWED"
        if not item.entity_evidence:
            return "ENTITY_EVIDENCE_MISSING"
        if item.published_at > fetched_at + timedelta(minutes=5):
            return "PUBLISHED_AT_IN_FUTURE"
        if item.event_time > item.published_at + timedelta(days=1):
            return "EVENT_TIME_AFTER_PUBLICATION"
        if item.available_at and item.available_at < item.published_at:
            return "AVAILABLE_BEFORE_PUBLICATION"
        return None
