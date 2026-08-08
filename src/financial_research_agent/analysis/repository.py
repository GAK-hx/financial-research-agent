from __future__ import annotations

from datetime import date

import pyarrow as pa
from pyiceberg.expressions import And, EqualTo, LessThanOrEqual

from financial_research_agent.analysis.schema import (
    FACTOR_RUNS_TABLE,
    FACTOR_VALUES_TABLE,
    TABLE_SCHEMAS,
)
from financial_research_agent.config import Settings
from financial_research_agent.repositories.iceberg import IcebergAdmin, IcebergRepository


class AnalysisRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.repository = IcebergRepository(settings)

    def bootstrap(self) -> list[str]:
        admin = IcebergAdmin(self.settings)
        admin.bootstrap_namespaces()
        created: list[str] = []
        for identifier, schema in TABLE_SCHEMAS.items():
            if not self.repository.table_exists(identifier):
                admin.create_table(identifier, schema)
                created.append(identifier)
        return created

    def append(self, identifier: str, table: pa.Table) -> int | None:
        if identifier not in TABLE_SCHEMAS:
            raise ValueError(f"analysis table is not writable: {identifier}")
        if table.num_rows == 0:
            raise ValueError("cannot append empty analysis result")
        target = self.repository.catalog.load_table(identifier)
        target.append(table)
        snapshot = target.current_snapshot()
        return snapshot.snapshot_id if snapshot else None

    def query_factor_values(
        self,
        *,
        universe_id: str,
        as_of_date: date,
        factor_names: list[str] | None = None,
    ) -> pa.Table:
        if not self.repository.table_exists(FACTOR_VALUES_TABLE):
            return pa.table({})
        table = self.repository.catalog.load_table(FACTOR_VALUES_TABLE)
        rows = table.scan(
            row_filter=And(
                EqualTo("universe_id", universe_id),
                LessThanOrEqual("as_of_date", as_of_date),
            )
        ).to_arrow()
        if rows.num_rows == 0:
            return rows
        frame = rows.to_pandas()
        latest_at = frame["as_of_date"].max()
        frame = frame[frame["as_of_date"] == latest_at]
        latest_run = frame.sort_values("computed_at").iloc[-1]["run_id"]
        frame = frame[frame["run_id"] == latest_run]
        if factor_names:
            frame = frame[frame["factor_name"].isin(factor_names)]
        return pa.Table.from_pandas(
            frame,
            schema=TABLE_SCHEMAS[FACTOR_VALUES_TABLE].as_arrow(),
            preserve_index=False,
        )

    def latest_run(self, universe_id: str, as_of_date: date) -> dict | None:
        if not self.repository.table_exists(FACTOR_RUNS_TABLE):
            return None
        table = self.repository.catalog.load_table(FACTOR_RUNS_TABLE)
        rows = table.scan(
            row_filter=And(
                EqualTo("universe_id", universe_id),
                LessThanOrEqual("as_of_date", as_of_date),
            )
        ).to_arrow()
        if rows.num_rows == 0:
            return None
        frame = rows.to_pandas().sort_values(["as_of_date", "finished_at"])
        return frame.iloc[-1].to_dict()

    def snapshot_id(self, identifier: str) -> int | None:
        if not self.repository.table_exists(identifier):
            return None
        snapshot = self.repository.catalog.load_table(identifier).current_snapshot()
        return snapshot.snapshot_id if snapshot else None
