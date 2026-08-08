from __future__ import annotations

import hashlib
import time
from datetime import date, datetime, timezone

from pydantic import BaseModel, Field, model_validator

from financial_research_agent.domain.models import Evidence, SourceReference, ToolResult
from financial_research_agent.knowledge.store import KnowledgeStore
from financial_research_agent.tools.base import FinancialTool, ToolDefinition


class EventSearchInput(BaseModel):
    stock_code: str = Field(pattern=r"^\d{6}$")
    start_date: date | None = None
    end_date: date | None = None
    query: str | None = Field(default=None, max_length=200)
    max_events: int = Field(default=8, ge=1, le=12)

    @model_validator(mode="after")
    def validate_dates(self) -> EventSearchInput:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date")
        return self


class EventSearchTool(FinancialTool):
    definition = ToolDefinition(
        name="event_search",
        version="1.0.0",
        description=(
            "Retrieve only ACTIVE, source-traceable company events from PostgreSQL by stock and "
            "time. Candidate, rejected and superseded events are never returned. Returns event Evidence."
        ),
        timeout_seconds=15,
        max_rows=12,
        data_domain="knowledge",
    )
    input_model = EventSearchInput

    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store

    async def execute(self, task_id: str, arguments: EventSearchInput) -> ToolResult:
        started = time.perf_counter()
        rows = await self.store.search_active(
            symbol=arguments.stock_code,
            query=arguments.query,
            start_date=arguments.start_date,
            end_date=arguments.end_date,
            limit=arguments.max_events,
        )
        if not rows:
            return ToolResult(
                task_id=task_id,
                success=False,
                error_code="EVENT_DATA_EMPTY",
                error_message="no ACTIVE events matched the controlled query",
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        evidence = []
        for event in rows:
            locator = f"knowledge://event/{event.event_id}"
            evidence.append(Evidence(
                evidence_id=f"event-{hashlib.sha256(locator.encode()).hexdigest()[:16]}",
                evidence_type="event",
                subject=event.symbol,
                statement=(
                    f"{event.title}；事件时间{event.event_time.isoformat()}，"
                    f"发布时间{event.published_at.isoformat()}。"
                ),
                data={
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "title": event.title,
                    "content": event.content,
                    "event_time": event.event_time,
                    "published_at": event.published_at,
                    "available_at": event.available_at,
                    "source_id": event.source_id,
                    "source_rank": event.source_rank,
                    "conflict_group": event.conflict_group,
                },
                source=SourceReference(
                    source_type="knowledge",
                    locator=locator,
                    observed_at=datetime.now(timezone.utc),
                    metadata={
                        "event_id": event.event_id,
                        "source_url": event.source_url,
                        "source_record_id": event.source_record_id,
                        "available_at": event.available_at.isoformat(),
                        "status": event.status.value,
                        "raw_locator": event.raw_locator,
                        "extraction_version": event.extraction_version,
                    },
                ),
            ))
        return ToolResult(
            task_id=task_id,
            success=True,
            evidence=evidence,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
