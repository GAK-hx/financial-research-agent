from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pandas as pd
import pyarrow as pa

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
from financial_research_agent.market.normalize import normalize_daily_market
from financial_research_agent.market.schema import BUSINESS_KEY, KLINE_DAILY_SCHEMA, KLINE_DAILY_TABLE
from financial_research_agent.market.source import DailyMarketSource
from financial_research_agent.repositories.iceberg import IcebergAdmin, IcebergRepository


class MarketIngestionService:
    def __init__(self, settings: Settings, source: DailyMarketSource) -> None:
        self.settings = settings
        self.source = source
        self.repository = IcebergRepository(settings)
        self.admin = IcebergAdmin(settings)
        self.raw_store = RawBatchStore(settings.lake_root)
        self.metadata_store = BatchMetadataStore(settings.lake_root)
        self.report_store = JsonArtifactStore(settings.lake_root, "quality_reports")

    def run(self, end_date: date | None = None) -> dict:
        run_id = f"market-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid4().hex[:8]}"
        end = end_date or date.today()
        self.admin.bootstrap_namespaces()
        if not self.repository.table_exists(KLINE_DAILY_TABLE):
            self.admin.create_table(KLINE_DAILY_TABLE, KLINE_DAILY_SCHEMA)

        report: dict = {
            "run_id": run_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "source": self.source.name,
            "table": KLINE_DAILY_TABLE,
            "stocks": [],
            "failed_stocks": [],
        }
        for symbol in self.settings.stock_codes:
            try:
                report["stocks"].append(self._ingest_stock(run_id, symbol, end))
            except Exception as exc:
                report["failed_stocks"].append({"stock_code": symbol, "error": str(exc)})
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["status"] = "success" if not report["failed_stocks"] else "warning"
        report["report_path"] = str(self.report_store.save(run_id, report))
        return report

    def _ingest_stock(self, run_id: str, symbol: str, end: date) -> dict:
        batch_id = f"{run_id}-{symbol}"
        existing = self.repository.scan(KLINE_DAILY_TABLE).to_pandas()
        symbol_existing = existing.loc[existing["stock_code"] == symbol] if not existing.empty else existing
        configured_start = datetime.strptime(self.settings.market_history_start, "%Y%m%d").date()
        if symbol_existing.empty:
            start = configured_start
        else:
            start = max(symbol_existing["trade_date"]) + timedelta(days=1)

        if start > end:
            return {"stock_code": symbol, "status": "up_to_date", "new_rows": 0}

        raw = self.source.fetch(
            symbol=symbol,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust=self.settings.market_adjust_type,
        )
        source_endpoint = str(raw.attrs.get("source_endpoint", self.source.endpoint))
        source_metadata = SourceMetadata(
            source=self.source.name,
            endpoint=source_endpoint,
            mapping_version=self.source.mapping_version,
            parameters={
                "symbol": symbol,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "adjust": self.settings.market_adjust_type,
            },
        )
        self.raw_store.write(f"market_daily_{symbol}", batch_id, pa.Table.from_pandas(raw, preserve_index=False))
        accepted, rejected, quality = normalize_daily_market(
            raw,
            symbol,
            self.settings.market_adjust_type,
            self.source.name,
            batch_id,
        )
        if not existing.empty and not accepted.empty:
            existing_keys = pd.MultiIndex.from_frame(existing[BUSINESS_KEY])
            incoming_keys = pd.MultiIndex.from_frame(accepted[BUSINESS_KEY])
            accepted = accepted.loc[~incoming_keys.isin(existing_keys)].reset_index(drop=True)
        if not rejected.empty:
            self.raw_store.write(
                f"market_daily_rejected_{symbol}",
                batch_id,
                pa.Table.from_pandas(rejected, preserve_index=False),
            )

        ingestion = IngestionBatch(
            batch_id=batch_id,
            dataset="kline_daily",
            tier=DataTier.CURATED,
            source=source_metadata,
            requested_start=start,
            requested_end=end,
            input_rows=len(raw),
            output_rows=len(accepted),
            rejected_rows=len(rejected),
        )
        if accepted.empty:
            completed = ingestion.model_copy(
                update={
                    "target_table": KLINE_DAILY_TABLE,
                    "finished_at": datetime.now(timezone.utc),
                    "status": BatchStatus.WARNING if len(rejected) else BatchStatus.SUCCESS,
                    "message": "no new accepted rows",
                }
            )
            self.metadata_store.save(completed)
        else:
            arrow_batch = pa.Table.from_pandas(accepted, preserve_index=False)
            completed = self.repository.append(
                KLINE_DAILY_TABLE,
                arrow_batch,
                ingestion,
                self.metadata_store,
            )
        return {
            "stock_code": symbol,
            "status": completed.status.value,
            "requested_start": start.isoformat(),
            "requested_end": end.isoformat(),
            "input_rows": len(raw),
            "new_rows": len(accepted),
            "rejected_rows": quality.rejected_rows,
            "snapshot_id": completed.snapshot_id,
            "batch_id": batch_id,
            "source_endpoint": source_endpoint,
        }
