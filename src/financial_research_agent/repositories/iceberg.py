from datetime import datetime, timezone

from pyiceberg.catalog import load_catalog
from pyiceberg.schema import Schema

from financial_research_agent.config import Settings
from financial_research_agent.data_management.models import BatchStatus, IngestionBatch
from financial_research_agent.data_management.storage import BatchMetadataStore

FORMAL_NAMESPACES = frozenset({"market", "financial", "knowledge", "metadata"})
ALL_NAMESPACES = (*sorted(FORMAL_NAMESPACES), "simulation")


def _namespace(identifier: str) -> str:
    parts = identifier.split(".")
    if len(parts) != 2 or not all(part.replace("_", "").isalnum() for part in parts):
        raise ValueError("table identifier must use namespace.table format")
    return parts[0]


class IcebergRepository:
    def __init__(self, settings: Settings) -> None:
        self.catalog = load_catalog(
            "default",
            type="sql",
            uri=settings.iceberg_catalog_uri,
            warehouse=settings.iceberg_warehouse,
        )

    def _validate_formal_identifier(self, identifier: str) -> None:
        namespace = _namespace(identifier)
        if namespace not in FORMAL_NAMESPACES:
            raise PermissionError(f"formal repository cannot access namespace: {namespace}")

    def table_exists(self, identifier: str) -> bool:
        self._validate_formal_identifier(identifier)
        try:
            self.catalog.load_table(identifier)
            return True
        except Exception:
            return False

    def scan(self, identifier: str):
        self._validate_formal_identifier(identifier)
        return self.catalog.load_table(identifier).scan().to_arrow()

    def append(
        self,
        identifier: str,
        batch,
        ingestion: IngestionBatch,
        metadata_store: BatchMetadataStore,
    ) -> IngestionBatch:
        self._validate_formal_identifier(identifier)
        if batch.num_rows == 0:
            raise ValueError("cannot append an empty batch")
        if ingestion.status != BatchStatus.RUNNING:
            raise ValueError("only a running ingestion batch can write data")
        if ingestion.output_rows != batch.num_rows:
            raise ValueError("ingestion output_rows must match the Arrow batch")
        table = self.catalog.load_table(identifier)
        table.append(batch)
        completed = ingestion.model_copy(
            update={
                "target_table": identifier,
                "snapshot_id": table.current_snapshot().snapshot_id,
                "finished_at": datetime.now(timezone.utc),
                "status": (
                    BatchStatus.WARNING if ingestion.rejected_rows else BatchStatus.SUCCESS
                ),
            }
        )
        metadata_store.save(completed)
        return completed


class IcebergAdmin:
    def __init__(self, settings: Settings) -> None:
        self.catalog = load_catalog(
            "default",
            type="sql",
            uri=settings.iceberg_catalog_uri,
            warehouse=settings.iceberg_warehouse,
        )

    def bootstrap_namespaces(self) -> list[str]:
        existing = {namespace[0] for namespace in self.catalog.list_namespaces()}
        created: list[str] = []
        for namespace in ALL_NAMESPACES:
            if namespace not in existing:
                self.catalog.create_namespace(namespace)
                created.append(namespace)
        return created

    def create_table(self, identifier: str, schema: Schema) -> None:
        namespace = _namespace(identifier)
        if namespace not in ALL_NAMESPACES:
            raise ValueError(f"unknown namespace: {namespace}")
        self.catalog.create_table(identifier, schema=schema)
