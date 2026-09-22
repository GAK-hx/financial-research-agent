from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from financial_research_agent.config import Settings, get_settings
from financial_research_agent.evaluation.run import load_named_dataset
from financial_research_agent.financial.schema import METRICS_TABLE
from financial_research_agent.market.schema import KLINE_DAILY_TABLE
from financial_research_agent.repositories.iceberg import IcebergRepository


class IcebergSnapshotEntry(BaseModel):
    table: str
    snapshot_id: int
    schema_id: int | None = None
    sequence_number: int | None = None
    timestamp_ms: int | None = None


class ReportSnapshotEntry(BaseModel):
    filename: str
    sha256: str
    size_bytes: int = Field(ge=1)


class EvaluationSnapshotManifest(BaseModel):
    manifest_version: str = "evaluation_snapshot_v1"
    dataset_name: str
    dataset_version: str
    dataset_sha256: str
    as_of_date: date
    captured_at: datetime
    business_timezone: str
    iceberg: list[IcebergSnapshotEntry] = Field(min_length=2)
    reports: list[ReportSnapshotEntry] = Field(min_length=1)
    retrieval: dict[str, str]
    fingerprint: str = ""

    def content_fingerprint(self) -> str:
        payload = self.model_dump(
            mode="json",
            exclude={"fingerprint", "captured_at"},
        )
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def verify(self, *, dataset_sha256: str, as_of_date: date) -> None:
        if self.dataset_sha256 != dataset_sha256:
            raise ValueError("evaluation snapshot dataset hash mismatch")
        if self.as_of_date != as_of_date:
            raise ValueError("evaluation snapshot as_of_date mismatch")
        if self.fingerprint != self.content_fingerprint():
            raise ValueError("evaluation snapshot fingerprint mismatch")

    def verify_inputs(
        self,
        *,
        iceberg: list[IcebergSnapshotEntry],
        reports: list[ReportSnapshotEntry],
        retrieval: dict[str, str],
    ) -> None:
        if iceberg != self.iceberg:
            raise ValueError("evaluation snapshot Iceberg input drift")
        if reports != self.reports:
            raise ValueError("evaluation snapshot report input drift")
        if retrieval != self.retrieval:
            raise ValueError("evaluation snapshot retrieval configuration drift")


def _current_iceberg(settings: Settings) -> list[IcebergSnapshotEntry]:
    repository = IcebergRepository(settings)
    entries: list[IcebergSnapshotEntry] = []
    for identifier in (KLINE_DAILY_TABLE, METRICS_TABLE):
        table = repository.catalog.load_table(identifier)
        snapshot = table.current_snapshot()
        if snapshot is None:
            raise ValueError(f"table has no current snapshot: {identifier}")
        entries.append(
            IcebergSnapshotEntry(
                table=identifier,
                snapshot_id=snapshot.snapshot_id,
                schema_id=getattr(snapshot, "schema_id", None),
                sequence_number=getattr(snapshot, "sequence_number", None),
                timestamp_ms=getattr(snapshot, "timestamp_ms", None),
            )
        )
    return entries


def _current_reports(settings: Settings) -> list[ReportSnapshotEntry]:
    reports_root = Path(settings.reports_dir)
    entries = [
        ReportSnapshotEntry(
            filename=path.name,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            size_bytes=path.stat().st_size,
        )
        for path in sorted(reports_root.glob("*.pdf"))
        if path.is_file() and path.stat().st_size > 0
    ]
    if not entries:
        raise ValueError(f"no report PDFs found in {reports_root}")
    return entries


def _current_retrieval(settings: Settings) -> dict[str, str]:
    return {
        "embedding_model": settings.rag_embedding_model,
        "collection": "research_reports_v1",
        "index_policy": "dense_baseline_v1",
    }


def capture_manifest(
    settings: Settings,
    dataset_name: str,
) -> EvaluationSnapshotManifest:
    dataset, dataset_sha256 = load_named_dataset(dataset_name)
    iceberg = _current_iceberg(settings)
    reports = _current_reports(settings)

    manifest = EvaluationSnapshotManifest(
        dataset_name=dataset_name,
        dataset_version=dataset.dataset_version,
        dataset_sha256=dataset_sha256,
        as_of_date=dataset.as_of_date,
        captured_at=datetime.now(timezone.utc),
        business_timezone=settings.business_timezone,
        iceberg=iceberg,
        reports=reports,
        retrieval=_current_retrieval(settings),
    )
    return manifest.model_copy(
        update={"fingerprint": manifest.content_fingerprint()}
    )


def load_and_verify_manifest(
    path: Path,
    *,
    dataset_sha256: str,
    as_of_date: date,
) -> EvaluationSnapshotManifest:
    manifest = EvaluationSnapshotManifest.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    manifest.verify(dataset_sha256=dataset_sha256, as_of_date=as_of_date)
    return manifest


def verify_current_inputs(
    settings: Settings,
    manifest: EvaluationSnapshotManifest,
) -> None:
    manifest.verify_inputs(
        iceberg=_current_iceberg(settings),
        reports=_current_reports(settings),
        retrieval=_current_retrieval(settings),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture immutable inputs for a reproducible evaluation run"
    )
    parser.add_argument(
        "--dataset",
        default="regression",
        choices=["regression", "holdout", "stability", "private_holdout"],
    )
    parser.add_argument(
        "--output",
        default="/artifacts/evaluation/snapshot_manifest.json",
    )
    args = parser.parse_args()
    manifest = capture_manifest(get_settings(), args.dataset)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "manifest": str(target),
                "fingerprint": manifest.fingerprint,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
