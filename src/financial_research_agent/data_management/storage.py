from __future__ import annotations

import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from financial_research_agent.data_management.models import IngestionBatch


class DuplicateBatchError(ValueError):
    pass


class BatchMetadataStore:
    """File-backed bootstrap store; Iceberg tables remain the analytical source of truth."""

    def __init__(self, lake_root: str | Path) -> None:
        self.root = Path(lake_root) / "metadata" / "ingestion_runs"

    def save(self, batch: IngestionBatch) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{batch.batch_id}.json"
        if target.exists():
            raise DuplicateBatchError(f"batch_id already exists: {batch.batch_id}")
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(batch.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, target)
        return target

    def load(self, batch_id: str) -> IngestionBatch:
        return IngestionBatch.model_validate_json(
            (self.root / f"{batch_id}.json").read_text(encoding="utf-8")
        )


class RawBatchStore:
    def __init__(self, lake_root: str | Path) -> None:
        self.root = Path(lake_root) / "raw"

    def write(self, dataset: str, batch_id: str, table: pa.Table) -> Path:
        if not dataset.replace("_", "").isalnum():
            raise ValueError("dataset may contain only letters, numbers, and underscores")
        target_dir = self.root / dataset / f"batch_id={batch_id}"
        target_dir.mkdir(parents=True, exist_ok=False)
        target = target_dir / "part-00000.parquet"
        pq.write_table(table, target, compression="zstd")
        return target

    def read(self, dataset: str, batch_id: str) -> pa.Table:
        path = self.root / dataset / f"batch_id={batch_id}" / "part-00000.parquet"
        return pq.ParquetFile(path).read()


class JsonArtifactStore:
    def __init__(self, lake_root: str | Path, category: str) -> None:
        self.root = Path(lake_root) / "metadata" / category

    def save(self, artifact_id: str, payload: dict) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{artifact_id}.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, target)
        return target
