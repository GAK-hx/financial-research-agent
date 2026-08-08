from __future__ import annotations

import json
import pyarrow as pa
from pyiceberg.catalog import load_catalog
from pyiceberg.io.pyarrow import schema_to_pyarrow
from pyiceberg.schema import Schema
from pyiceberg.types import NestedField, StringType

from financial_research_agent.config import Settings
from financial_research_agent.knowledge.models import RawKnowledgeItem, SourceBatch


RAW_EVENT_TABLE = "knowledge.raw_events_v1"


RAW_EVENT_SCHEMA = Schema(
    NestedField(1, "source_id", StringType(), required=True),
    NestedField(2, "source_record_id", StringType(), required=True),
    NestedField(3, "raw_version", StringType(), required=True),
    NestedField(4, "symbol", StringType(), required=True),
    NestedField(5, "event_type", StringType(), required=True),
    NestedField(6, "published_at", StringType(), required=True),
    NestedField(7, "fetched_at", StringType(), required=True),
    NestedField(8, "source_url", StringType(), required=True),
    NestedField(9, "payload_json", StringType(), required=True),
)


class KnowledgeLake:
    def __init__(self, settings: Settings, table_name: str = RAW_EVENT_TABLE) -> None:
        self.catalog = load_catalog(
            "knowledge",
            type="sql",
            uri=settings.iceberg_catalog_uri,
            warehouse=settings.iceberg_warehouse,
        )
        self.table_name = table_name

    def prepare(self) -> None:
        namespaces = {item[0] for item in self.catalog.list_namespaces()}
        if "knowledge" not in namespaces:
            self.catalog.create_namespace("knowledge")
        try:
            self.catalog.load_table(self.table_name)
        except Exception:
            self.catalog.create_table(self.table_name, schema=RAW_EVENT_SCHEMA)

    def append(self, batch: SourceBatch) -> tuple[str, int | None]:
        self.prepare()
        if not batch.records:
            return f"iceberg://{self.table_name}", None
        rows = [self._row(batch, item) for item in batch.records]
        table = self.catalog.load_table(self.table_name)
        table.append(
            pa.Table.from_pylist(rows, schema=schema_to_pyarrow(RAW_EVENT_SCHEMA))
        )
        snapshot = table.current_snapshot()
        snapshot_id = snapshot.snapshot_id if snapshot else None
        return f"iceberg://{self.table_name}?snapshot_id={snapshot_id}", snapshot_id

    @staticmethod
    def _row(batch: SourceBatch, item: RawKnowledgeItem) -> dict[str, str]:
        return {
            "source_id": batch.source_id,
            "source_record_id": item.source_record_id,
            "raw_version": item.raw_version,
            "symbol": item.symbol,
            "event_type": item.event_type,
            "published_at": item.published_at.isoformat(),
            "fetched_at": batch.fetched_at.isoformat(),
            "source_url": item.source_url,
            "payload_json": json.dumps(item.model_dump(mode="json"), ensure_ascii=False),
        }
