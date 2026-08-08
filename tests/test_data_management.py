import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
from pydantic import ValidationError
from pyiceberg.schema import Schema
from pyiceberg.types import DoubleType, NestedField, StringType

from financial_research_agent.config import Settings
from financial_research_agent.data_management.models import (
    BatchStatus,
    DataQualityResult,
    DataTier,
    IngestionBatch,
    SourceMetadata,
)
from financial_research_agent.data_management.storage import (
    BatchMetadataStore,
    DuplicateBatchError,
    RawBatchStore,
)
from financial_research_agent.repositories.iceberg import IcebergAdmin, IcebergRepository


def source() -> SourceMetadata:
    return SourceMetadata(source="akshare", endpoint="stock_zh_a_hist", mapping_version="v1")


class DataManagementTests(unittest.TestCase):
    def test_quality_counts_must_balance(self) -> None:
        with self.assertRaises(ValidationError):
            DataQualityResult(checked_rows=3, accepted_rows=2, rejected_rows=0)

    def test_finished_batch_requires_finished_at(self) -> None:
        with self.assertRaises(ValidationError):
            IngestionBatch(
                batch_id="batch-1",
                dataset="daily_market",
                tier=DataTier.CURATED,
                source=source(),
                status=BatchStatus.SUCCESS,
            )

    def test_batch_metadata_is_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = BatchMetadataStore(directory)
            batch = IngestionBatch(
                batch_id="batch-1",
                dataset="daily_market",
                tier=DataTier.RAW,
                source=source(),
                finished_at=datetime.now(timezone.utc),
                input_rows=2,
                output_rows=2,
                status=BatchStatus.SUCCESS,
            )
            store.save(batch)
            self.assertEqual(store.load("batch-1"), batch)
            with self.assertRaises(DuplicateBatchError):
                store.save(batch)

    def test_raw_store_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = RawBatchStore(directory)
            table = pa.table({"symbol": ["600519"], "close": [1500.0]})
            path = store.write("daily_market", "batch-1", table)
            self.assertTrue(path.exists())
            self.assertEqual(store.read("daily_market", "batch-1").to_pydict(), table.to_pydict())

    def test_formal_repository_rejects_simulation_before_catalog_access(self) -> None:
        repository = IcebergRepository.__new__(IcebergRepository)
        with self.assertRaises(PermissionError):
            repository.scan("simulation.mock_ticks")

    def test_repository_requires_qualified_identifier(self) -> None:
        repository = IcebergRepository.__new__(IcebergRepository)
        with self.assertRaises(ValueError):
            repository.table_exists("daily_market")

    def test_catalog_bootstrap_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                iceberg_catalog_uri=f"sqlite:///{root}/catalog.db",
                iceberg_warehouse=f"file://{root}/warehouse",
                lake_root=str(root),
            )
            admin = IcebergAdmin(settings)
            self.assertEqual(
                set(admin.bootstrap_namespaces()),
                {"market", "financial", "knowledge", "metadata", "simulation"},
            )
            self.assertEqual(admin.bootstrap_namespaces(), [])

    def test_create_append_and_scan_formal_table(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                iceberg_catalog_uri=f"sqlite:///{root}/catalog.db",
                iceberg_warehouse=f"file://{root}/warehouse",
                lake_root=str(root),
            )
            admin = IcebergAdmin(settings)
            admin.bootstrap_namespaces()
            admin.create_table(
                "market.daily_test",
                Schema(
                    NestedField(1, "symbol", StringType(), required=False),
                    NestedField(2, "close", DoubleType(), required=False),
                ),
            )
            repository = IcebergRepository(settings)
            metadata_store = BatchMetadataStore(root)
            completed = repository.append(
                "market.daily_test",
                pa.table({"symbol": ["600519"], "close": [1500.0]}),
                IngestionBatch(
                    batch_id="iceberg-batch-1",
                    dataset="daily_test",
                    tier=DataTier.CURATED,
                    source=source(),
                    input_rows=1,
                    output_rows=1,
                ),
                metadata_store,
            )
            self.assertIsInstance(completed.snapshot_id, int)
            self.assertEqual(completed.status, BatchStatus.SUCCESS)
            self.assertEqual(metadata_store.load("iceberg-batch-1"), completed)
            self.assertEqual(repository.scan("market.daily_test").num_rows, 1)


if __name__ == "__main__":
    unittest.main()
