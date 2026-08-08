from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Protocol

from financial_research_agent.knowledge.models import RawKnowledgeItem, SourceBatch


class KnowledgeSource(Protocol):
    source_id: str
    source_rank: int
    license_name: str

    async def fetch(self, cursor: str | None, limit: int) -> SourceBatch: ...


class LocalJsonKnowledgeSource:
    """Licensed local fixture adapter used until an external source is approved."""

    source_id = "local_demo_events"
    source_rank = 3
    license_name = "project-demo-fixture"

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else Path(
            str(files("financial_research_agent.knowledge").joinpath("samples/events.json"))
        )

    async def fetch(self, cursor: str | None, limit: int) -> SourceBatch:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        records = [RawKnowledgeItem.model_validate(item) for item in payload["events"]]
        offset = int(cursor or 0)
        selected = records[offset : offset + limit]
        next_offset = offset + len(selected)
        return SourceBatch(
            source_id=self.source_id,
            source_rank=self.source_rank,
            license_name=self.license_name,
            cursor_before=cursor,
            cursor_after=str(next_offset),
            fetched_at=datetime.now(timezone.utc),
            records=selected,
        )
