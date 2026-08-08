from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd
import pyarrow as pa
from pyiceberg.io.pyarrow import schema_to_pyarrow

from financial_research_agent.config import Settings
from financial_research_agent.data_management.models import (
    BatchStatus,
    DataTier,
    IngestionBatch,
    SourceMetadata,
)
from financial_research_agent.data_management.storage import (
    BatchMetadataStore,
    JsonArtifactStore,
    RawBatchStore,
)
from financial_research_agent.financial.normalize import calculate_metrics, normalize_statement
from financial_research_agent.financial.schema import (
    BALANCE_TABLE,
    CASH_FLOW_TABLE,
    INCOME_TABLE,
    METRICS_TABLE,
    TABLE_SCHEMAS,
)
from financial_research_agent.financial.source import FinancialStatementSource
from financial_research_agent.repositories.iceberg import IcebergAdmin, IcebergRepository

STATEMENT_TABLES = {
    "income": INCOME_TABLE,
    "balance": BALANCE_TABLE,
    "cash_flow": CASH_FLOW_TABLE,
}


class FinancialIngestionService:
    def __init__(self, settings: Settings, source: FinancialStatementSource) -> None:
        self.settings = settings
        self.source = source
        self.repository = IcebergRepository(settings)
        self.admin = IcebergAdmin(settings)
        self.raw_store = RawBatchStore(settings.lake_root)
        self.metadata_store = BatchMetadataStore(settings.lake_root)
        self.report_store = JsonArtifactStore(settings.lake_root, "financial_quality_reports")

    def run(self) -> dict:
        run_id = f"financial-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid4().hex[:8]}"
        self.admin.bootstrap_namespaces()
        for table, schema in TABLE_SCHEMAS.items():
            if not self.repository.table_exists(table):
                self.admin.create_table(table, schema)
        report = {
            "run_id": run_id,
            "source": self.source.name,
            "mapping_version": self.source.mapping_version,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "stocks": [],
            "failed_stocks": [],
        }
        for stock_code in self.settings.stock_codes:
            try:
                report["stocks"].append(self._ingest_stock(run_id, stock_code))
            except Exception as exc:
                report["failed_stocks"].append({"stock_code": stock_code, "error": str(exc)})
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["status"] = "success" if not report["failed_stocks"] else "warning"
        report["report_path"] = str(self.report_store.save(run_id, report))
        return report

    def _ingest_stock(self, run_id: str, stock_code: str) -> dict:
        normalized: dict[str, pd.DataFrame] = {}
        stock_result = {"stock_code": stock_code, "statements": {}, "metrics": {}}
        for statement, table in STATEMENT_TABLES.items():
            batch_id = f"{run_id}-{stock_code}-{statement}"
            raw = self.source.fetch(stock_code, statement)
            self.raw_store.write(
                f"financial_{statement}_{stock_code}",
                batch_id,
                pa.Table.from_pandas(raw, preserve_index=False),
            )
            accepted, rejected = normalize_statement(
                raw, statement, stock_code, self.source.name, batch_id
            )
            normalized[statement] = accepted
            if not rejected.empty:
                self.raw_store.write(
                    f"financial_{statement}_rejected_{stock_code}",
                    batch_id,
                    pa.Table.from_pandas(rejected, preserve_index=False),
                )
            written, snapshot_id = self._append_new(
                table=table,
                frame=accepted,
                batch_id=batch_id,
                dataset=statement,
                input_rows=len(raw),
                rejected_rows=len(rejected),
                stock_code=stock_code,
            )
            stock_result["statements"][statement] = {
                "input_rows": len(raw),
                "accepted_rows": len(accepted),
                "rejected_rows": len(rejected),
                "new_rows": written,
                "snapshot_id": snapshot_id,
            }

        metrics_batch_id = f"{run_id}-{stock_code}-metrics"
        metrics = calculate_metrics(
            normalized["income"],
            normalized["balance"],
            normalized["cash_flow"],
            metrics_batch_id,
            self.source.name,
        )
        written, snapshot_id = self._append_new(
            table=METRICS_TABLE,
            frame=metrics,
            batch_id=metrics_batch_id,
            dataset="financial_metrics",
            input_rows=len(metrics),
            rejected_rows=0,
            stock_code=stock_code,
        )
        stock_result["metrics"] = {
            "available_periods": len(metrics),
            "new_rows": written,
            "snapshot_id": snapshot_id,
            "min_report_date": str(metrics["report_date"].min()),
            "max_report_date": str(metrics["report_date"].max()),
        }
        return stock_result

    def _append_new(
        self,
        table: str,
        frame: pd.DataFrame,
        batch_id: str,
        dataset: str,
        input_rows: int,
        rejected_rows: int,
        stock_code: str,
    ) -> tuple[int, int | None]:
        existing = self.repository.scan(table).to_pandas()
        new_frame = frame
        if not existing.empty and not frame.empty:
            existing_keys = pd.MultiIndex.from_frame(existing[["stock_code", "report_date"]])
            incoming_keys = pd.MultiIndex.from_frame(frame[["stock_code", "report_date"]])
            new_frame = frame.loc[~incoming_keys.isin(existing_keys)].reset_index(drop=True)
        source_metadata = SourceMetadata(
            source=self.source.name,
            endpoint=self.source.endpoint,
            mapping_version=self.source.mapping_version,
            parameters={"stock_code": stock_code, "statement": dataset},
        )
        ingestion = IngestionBatch(
            batch_id=batch_id,
            dataset=dataset,
            tier=DataTier.CURATED,
            source=source_metadata,
            input_rows=input_rows,
            output_rows=len(new_frame),
            rejected_rows=rejected_rows,
        )
        if new_frame.empty:
            snapshot = self.repository.catalog.load_table(table).current_snapshot()
            completed = ingestion.model_copy(
                update={
                    "target_table": table,
                    "snapshot_id": snapshot.snapshot_id if snapshot else None,
                    "finished_at": datetime.now(timezone.utc),
                    "status": BatchStatus.WARNING if rejected_rows else BatchStatus.SUCCESS,
                    "message": "no new rows",
                }
            )
            self.metadata_store.save(completed)
        else:
            arrow = pa.Table.from_pandas(
                new_frame,
                schema=schema_to_pyarrow(TABLE_SCHEMAS[table]),
                preserve_index=False,
                safe=False,
            )
            completed = self.repository.append(table, arrow, ingestion, self.metadata_store)
        return len(new_frame), completed.snapshot_id
