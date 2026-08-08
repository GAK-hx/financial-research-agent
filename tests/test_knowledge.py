from __future__ import annotations

import unittest
from datetime import datetime, timezone

from financial_research_agent.knowledge.models import (
    KnowledgeEvent,
    KnowledgeEventStatus,
    RawKnowledgeItem,
    SourceBatch,
)
from financial_research_agent.knowledge.pipeline import KnowledgePipeline


def raw_item(*, record_id: str, symbol: str = "600519", content: str | None = None):
    return RawKnowledgeItem(
        source_record_id=record_id,
        symbol=symbol,
        event_type="company_update",
        title="渠道改革事件",
        content=content or "渠道改革持续推进，本记录用于知识状态机验证。",
        source_url=f"https://example.invalid/{record_id}",
        event_time=datetime(2026, 5, 2, 1, 0, tzinfo=timezone.utc),
        published_at=datetime(2026, 5, 2, 1, 30, tzinfo=timezone.utc),
        available_at=datetime(2026, 5, 2, 1, 35, tzinfo=timezone.utc),
        entity_evidence=[f"正文明确关联股票代码{symbol}"],
    )


class FakeSource:
    source_id = "licensed_fixture"
    source_rank = 2
    license_name = "test-license"

    def __init__(self, records):
        self.records = records

    async def fetch(self, cursor, limit):
        return SourceBatch(
            source_id=self.source_id,
            source_rank=self.source_rank,
            license_name=self.license_name,
            cursor_before=cursor,
            cursor_after="1",
            fetched_at=datetime.now(timezone.utc),
            records=self.records[:limit],
        )


class FakeLake:
    def append(self, batch):
        return "iceberg://knowledge.raw_events_v1?snapshot_id=1", 1


class FakeStore:
    def __init__(self):
        self.events: dict[str, KnowledgeEvent] = {}
        self.cursor_value = None

    async def cursor(self, source_id):
        return self.cursor_value

    async def save_cursor(self, **values):
        self.cursor_value = values["cursor"]

    async def create_candidate(self, event):
        if event.event_id in self.events:
            return self.events[event.event_id], False
        self.events[event.event_id] = event
        return event, True

    async def find_active_by_canonical(self, canonical_key, exclude_event_id=None):
        return [
            item
            for item in self.events.values()
            if item.canonical_key == canonical_key
            and item.status == KnowledgeEventStatus.ACTIVE
            and item.event_id != exclude_event_id
        ]

    async def transition(self, event_id, to_status, **values):
        event = self.events[event_id].model_copy(
            update={
                "status": to_status,
                "conflict_group": values.get("conflict_group"),
                "rejection_reason": values.get("rejection_reason"),
            }
        )
        self.events[event_id] = event
        return event

    async def mark_conflict(self, event_id, conflict_group):
        self.events[event_id] = self.events[event_id].model_copy(
            update={"conflict_group": conflict_group}
        )


class KnowledgePipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_activation_rejection_and_rerun_idempotency(self):
        store = FakeStore()
        source = FakeSource(
            [raw_item(record_id="valid"), raw_item(record_id="rejected", symbol="000001")]
        )
        pipeline = KnowledgePipeline(
            source=source,
            lake=FakeLake(),
            store=store,
            allowed_symbols={"600519"},
        )
        first = await pipeline.run_once()
        self.assertEqual((first.active, first.rejected), (1, 1))
        self.assertEqual(
            {item.status for item in store.events.values()},
            {KnowledgeEventStatus.ACTIVE, KnowledgeEventStatus.REJECTED},
        )
        second = await pipeline.run_once()
        self.assertEqual(second.duplicates, 2)

    async def test_conflicting_sources_remain_visible(self):
        store = FakeStore()
        first = KnowledgePipeline(
            source=FakeSource([
                raw_item(
                    record_id="source-a",
                    content="渠道改革版本甲，包含足够长度的知识状态机验证文本。",
                )
            ]),
            lake=FakeLake(),
            store=store,
            allowed_symbols={"600519"},
        )
        await first.run_once()
        second_source = FakeSource([
            raw_item(
                record_id="source-b",
                content="渠道改革版本乙，包含足够长度且不同的知识状态机验证文本。",
            )
        ])
        second_source.source_id = "licensed_fixture_b"
        second = KnowledgePipeline(
            source=second_source,
            lake=FakeLake(),
            store=store,
            allowed_symbols={"600519"},
        )
        result = await second.run_once()
        self.assertEqual(result.conflicts, 1)
        self.assertTrue(all(item.conflict_group for item in store.events.values()))


if __name__ == "__main__":
    unittest.main()
