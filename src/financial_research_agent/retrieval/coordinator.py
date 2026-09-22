from __future__ import annotations

import asyncio
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

from sqlalchemy import desc, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import AnalysisTask, QuerySpec, ToolResult
from financial_research_agent.persistence.models import (
    AnalysisArtifactRecord,
    ArtifactDependencyRecord,
    JobWorkDependencyRecord,
    ResearchJobRecord,
    RetrievalSnapshotRecord,
    RetrievalWorkUnitRecord,
)
from financial_research_agent.retrieval.models import (
    AnalysisArtifact,
    ArtifactVisibility,
    AtomicQueryKey,
    CacheDecision,
    CacheResolution,
    RetrievalMetrics,
    RetrievalSnapshot,
    WorkStatus,
    canonical_hash,
)
from financial_research_agent.shared_state import build_shared_state


def _utc(
    value: date | datetime | str | None, *, end: bool = False
) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            value = date.fromisoformat(value)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.combine(value, time.max if end else time.min, timezone.utc)


def atomic_key_for_task(
    task: AnalysisTask,
    query: QuerySpec,
    *,
    domain: str,
    tenant_id: str,
    policy_version: str,
) -> AtomicQueryKey:
    arguments = dict(task.arguments)
    stock_code = arguments.pop("stock_code", None)
    stock_codes = arguments.get("stock_codes")
    if stock_code is None and isinstance(stock_codes, list) and len(stock_codes) == 1:
        stock_code = stock_codes[0]
    start = arguments.pop("start_date", query.start_date)
    end = arguments.pop("end_date", query.end_date)
    topic = str(arguments.pop("query", "") or "")
    if domain == "public_web":
        topic = "|".join(
            ["event", *sorted(set(query.dimensions))]
        )[:200]
    visibility = (
        ArtifactVisibility.TENANT
        if domain in {"memory", "private_upload"}
        else ArtifactVisibility.PUBLIC
    )
    return AtomicQueryKey(
        stock_code=stock_code,
        domain=domain,
        topic=topic,
        window_start=_utc(start),
        window_end=_utc(end, end=True),
        provider_policy_version=policy_version,
        visibility=visibility,
        tenant_id=tenant_id if visibility == ArtifactVisibility.TENANT else None,
        parameters={"tool": task.tool_name.value, **arguments},
    )


def _snapshot(record: RetrievalSnapshotRecord) -> RetrievalSnapshot:
    result = ToolResult.model_validate(record.result_payload)
    return RetrievalSnapshot(
        snapshot_id=record.snapshot_id,
        atomic_key=AtomicQueryKey.model_validate(record.atomic_key),
        key_hash=record.key_hash,
        generation=record.generation,
        source_version=record.source_version,
        result=result,
        evidence_hash=record.evidence_hash,
        watermark=record.watermark,
        created_at=record.created_at,
        refreshed_at=record.refreshed_at,
        expires_at=record.expires_at,
    )


class PostgresRetrievalCoordinator:
    """PostgreSQL-backed single-flight coordinator for public tool results."""

    def __init__(
        self,
        sessions,
        settings: Settings,
        *,
        worker_id: str | None = None,
        shared_state=None,
    ) -> None:
        self.sessions = sessions
        self.settings = settings
        self.worker_id = worker_id or f"retrieval-{uuid4().hex[:12]}"
        self.metrics = Counter()
        self.shared_state = shared_state or build_shared_state(settings)
        self._owns_shared_state = shared_state is None

    async def aclose(self) -> None:
        if self._owns_shared_state:
            await self.shared_state.aclose()

    async def resolve(
        self,
        key: AtomicQueryKey,
        *,
        run_id: str,
        task_id: str,
    ) -> CacheResolution:
        now = datetime.now(timezone.utc)
        key_hash = key.cache_key
        hot = await self.shared_state.get_metadata("retrieval", key_hash)
        async with self.sessions.begin() as session:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": f"retrieval:{key_hash}"},
            )
            snapshot_record = None
            if hot and hot.get("snapshot_id"):
                candidate = await session.get(
                    RetrievalSnapshotRecord, str(hot["snapshot_id"])
                )
                if candidate is not None and candidate.key_hash == key_hash:
                    snapshot_record = candidate
            if snapshot_record is None:
                snapshot_record = await session.scalar(
                    select(RetrievalSnapshotRecord)
                    .where(RetrievalSnapshotRecord.key_hash == key_hash)
                    .order_by(desc(RetrievalSnapshotRecord.generation))
                    .limit(1)
                )
            if snapshot_record is not None and snapshot_record.expires_at > now:
                work = await session.get(
                    RetrievalWorkUnitRecord, snapshot_record.work_unit_id
                )
                await self._attach(session, run_id, task_id, work, CacheDecision.FRESH)
                self.metrics[CacheDecision.FRESH.value] += 1
                self.metrics["external_calls_saved"] += 1
                return CacheResolution(
                    decision=CacheDecision.FRESH,
                    key_hash=key_hash,
                    work_unit_id=snapshot_record.work_unit_id,
                    snapshot=_snapshot(snapshot_record),
                )
            active = await session.scalar(
                select(RetrievalWorkUnitRecord)
                .where(
                    RetrievalWorkUnitRecord.key_hash == key_hash,
                    RetrievalWorkUnitRecord.status == WorkStatus.LEASED.value,
                    RetrievalWorkUnitRecord.lease_expires_at > now,
                )
                .order_by(desc(RetrievalWorkUnitRecord.generation))
                .limit(1)
            )
            if active is not None:
                active.waiter_count += 1
                await self._attach(
                    session, run_id, task_id, active, CacheDecision.INFLIGHT
                )
                self.metrics[CacheDecision.INFLIGHT.value] += 1
                self.metrics["inflight_joins"] += 1
                return CacheResolution(
                    decision=CacheDecision.INFLIGHT,
                    key_hash=key_hash,
                    work_unit_id=active.id,
                    lease_owner=active.lease_owner,
                    retry_after_seconds=self.settings.retrieval_join_poll_seconds,
                )
            last_generation = max(
                snapshot_record.generation if snapshot_record else 0,
                int(
                    await session.scalar(
                        select(RetrievalWorkUnitRecord.generation)
                        .where(RetrievalWorkUnitRecord.key_hash == key_hash)
                        .order_by(desc(RetrievalWorkUnitRecord.generation))
                        .limit(1)
                    )
                    or 0
                ),
            )
            decision = CacheDecision.STALE if snapshot_record is not None else CacheDecision.MISS
            work = RetrievalWorkUnitRecord(
                id=uuid4().hex,
                key_hash=key_hash,
                generation=last_generation + 1,
                atomic_key=key.model_dump(mode="json"),
                visibility=key.visibility.value,
                tenant_id=key.tenant_id,
                status=WorkStatus.LEASED.value,
                lease_owner=self.worker_id,
                lease_expires_at=now + timedelta(seconds=self.settings.retrieval_lease_seconds),
                attempt_count=1,
            )
            session.add(work)
            await session.flush()
            await self._attach(session, run_id, task_id, work, decision)
            self.metrics[decision.value] += 1
            return CacheResolution(
                decision=decision,
                key_hash=key_hash,
                work_unit_id=work.id,
                lease_owner=self.worker_id,
                snapshot=_snapshot(snapshot_record) if snapshot_record else None,
            )

    async def _attach(self, session, run_id, task_id, work, decision) -> None:
        if work is None:
            return
        exists = await session.scalar(
            select(ResearchJobRecord.run_id).where(ResearchJobRecord.run_id == run_id)
        )
        if exists is None:
            return
        await session.execute(
            pg_insert(JobWorkDependencyRecord)
            .values(
                id=uuid4().hex,
                run_id=run_id,
                task_id=task_id,
                work_unit_id=work.id,
                cache_decision=decision.value,
            )
            .on_conflict_do_nothing()
        )

    async def wait_for_snapshot(self, resolution: CacheResolution) -> RetrievalSnapshot | None:
        if resolution.work_unit_id is None:
            return None
        deadline = asyncio.get_running_loop().time() + self.settings.retrieval_join_timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            async with self.sessions() as session:
                record = await session.scalar(
                    select(RetrievalSnapshotRecord).where(
                        RetrievalSnapshotRecord.work_unit_id == resolution.work_unit_id
                    )
                )
                if record is not None:
                    self.metrics["external_calls_saved"] += 1
                    return _snapshot(record)
                work = await session.get(
                    RetrievalWorkUnitRecord, resolution.work_unit_id
                )
                if work is None or work.status in {
                    WorkStatus.FAILED.value,
                    WorkStatus.CANCELLED.value,
                }:
                    return None
            await asyncio.sleep(self.settings.retrieval_join_poll_seconds)
        return None

    async def renew(self, resolution: CacheResolution) -> bool:
        if resolution.work_unit_id is None:
            return False
        now = datetime.now(timezone.utc)
        async with self.sessions.begin() as session:
            result = await session.execute(
                update(RetrievalWorkUnitRecord)
                .where(
                    RetrievalWorkUnitRecord.id == resolution.work_unit_id,
                    RetrievalWorkUnitRecord.status == WorkStatus.LEASED.value,
                    RetrievalWorkUnitRecord.lease_owner == self.worker_id,
                )
                .values(
                    lease_expires_at=now
                    + timedelta(seconds=self.settings.retrieval_lease_seconds)
                )
            )
            return result.rowcount == 1

    async def complete(
        self,
        resolution: CacheResolution,
        key: AtomicQueryKey,
        result: ToolResult,
        *,
        source_version: str,
        ttl_seconds: int,
        watermark: datetime | None = None,
    ) -> RetrievalSnapshot:
        if not resolution.work_unit_id:
            raise ValueError("cache resolution has no work unit")
        now = datetime.now(timezone.utc)
        evidence_hash = canonical_hash(
            [item.model_dump(mode="json") for item in result.evidence]
        )
        async with self.sessions.begin() as session:
            work = await session.get(
                RetrievalWorkUnitRecord,
                resolution.work_unit_id,
                with_for_update=True,
            )
            if work is None:
                raise RuntimeError("RETRIEVAL_WORK_NOT_FOUND")
            existing = await session.scalar(
                select(RetrievalSnapshotRecord).where(
                    RetrievalSnapshotRecord.work_unit_id == work.id
                )
            )
            if existing is not None:
                snapshot = _snapshot(existing)
            else:
                record = RetrievalSnapshotRecord(
                    snapshot_id=uuid4().hex,
                    work_unit_id=work.id,
                    key_hash=key.cache_key,
                    generation=work.generation,
                    atomic_key=key.model_dump(mode="json"),
                    source_version=source_version,
                    result_payload=result.model_dump(mode="json"),
                    evidence_hash=evidence_hash,
                    watermark=watermark,
                    refreshed_at=now,
                    expires_at=now + timedelta(seconds=ttl_seconds),
                )
                session.add(record)
                work.status = WorkStatus.SUCCEEDED.value
                work.lease_owner = None
                work.lease_expires_at = None
                await session.flush()
                await session.refresh(record)
                snapshot = _snapshot(record)
        await self.shared_state.set_metadata(
            "retrieval",
            key.cache_key,
            {
                "snapshot_id": snapshot.snapshot_id,
                "generation": snapshot.generation,
                "evidence_hash": snapshot.evidence_hash,
                "expires_at": snapshot.expires_at.isoformat(),
            },
            ttl_seconds=min(ttl_seconds, self.settings.redis_metadata_ttl_seconds),
        )
        return snapshot

    async def fail(self, resolution: CacheResolution, error_code: str) -> None:
        if resolution.work_unit_id is None:
            return
        async with self.sessions.begin() as session:
            await session.execute(
                update(RetrievalWorkUnitRecord)
                .where(RetrievalWorkUnitRecord.id == resolution.work_unit_id)
                .values(
                    status=WorkStatus.FAILED.value,
                    lease_owner=None,
                    lease_expires_at=None,
                    last_error=error_code[:256],
                )
            )

    async def get_analysis(self, analysis_key: str) -> AnalysisArtifact | None:
        now = datetime.now(timezone.utc)
        hot = await self.shared_state.get_metadata("analysis", analysis_key)
        async with self.sessions() as session:
            record = None
            if hot and hot.get("artifact_id"):
                candidate = await session.get(
                    AnalysisArtifactRecord, str(hot["artifact_id"])
                )
                if (
                    candidate is not None
                    and candidate.analysis_key == analysis_key
                    and candidate.validated
                    and candidate.expires_at > now
                ):
                    record = candidate
            if record is None:
                record = await session.scalar(
                    select(AnalysisArtifactRecord).where(
                        AnalysisArtifactRecord.analysis_key == analysis_key,
                        AnalysisArtifactRecord.validated.is_(True),
                        AnalysisArtifactRecord.expires_at > now,
                    )
                )
            if record is None:
                return None
            for snapshot_id, expected_hash in record.snapshot_dependencies.items():
                original = await session.get(RetrievalSnapshotRecord, snapshot_id)
                if original is None:
                    return None
                latest = await session.scalar(
                    select(RetrievalSnapshotRecord)
                    .where(RetrievalSnapshotRecord.key_hash == original.key_hash)
                    .order_by(desc(RetrievalSnapshotRecord.generation))
                    .limit(1)
                )
                if latest is None or latest.evidence_hash != expected_hash:
                    return None
            artifact = AnalysisArtifact.model_validate(
                {
                    column: getattr(record, column)
                    for column in AnalysisArtifact.model_fields
                }
            )
        await self.shared_state.set_metadata(
            "analysis",
            analysis_key,
            {
                "artifact_id": artifact.artifact_id,
                "expires_at": artifact.expires_at.isoformat(),
                "validated": True,
            },
            ttl_seconds=self.settings.redis_metadata_ttl_seconds,
        )
        return artifact

    async def put_analysis(self, artifact: AnalysisArtifact) -> None:
        if not artifact.validated:
            raise ValueError("only validated analysis artifacts may be shared")
        persisted_id = artifact.artifact_id
        async with self.sessions.begin() as session:
            values = {
                "artifact_id": artifact.artifact_id,
                "analysis_key": artifact.analysis_key,
                "analysis_type": artifact.analysis_type,
                "subjects": artifact.subjects,
                "snapshot_dependencies": artifact.snapshot_dependencies,
                "skill_versions": artifact.skill_versions,
                "model_id": artifact.model_id,
                "prompt_version": artifact.prompt_version,
                "policy_version": artifact.policy_version,
                "payload": artifact.payload,
                "validated": artifact.validated,
                "visibility": artifact.visibility.value,
                "tenant_id": artifact.tenant_id,
                "created_at": artifact.created_at,
                "expires_at": artifact.expires_at,
            }
            persisted_id = await session.scalar(
                pg_insert(AnalysisArtifactRecord)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[AnalysisArtifactRecord.analysis_key],
                    set_={
                        "payload": artifact.payload,
                        "validated": True,
                        "expires_at": artifact.expires_at,
                        "snapshot_dependencies": artifact.snapshot_dependencies,
                    },
                )
                .returning(AnalysisArtifactRecord.artifact_id)
            )
            persisted_id = persisted_id or artifact.artifact_id
            snapshots = (
                await session.execute(
                    select(RetrievalSnapshotRecord).where(
                        RetrievalSnapshotRecord.snapshot_id.in_(
                            list(artifact.snapshot_dependencies)
                        )
                    )
                )
            ).scalars()
            for snapshot in snapshots:
                await session.execute(
                    pg_insert(ArtifactDependencyRecord)
                    .values(
                        id=uuid4().hex,
                        artifact_id=persisted_id,
                        snapshot_id=snapshot.snapshot_id,
                        evidence_hash=snapshot.evidence_hash,
                    )
                    .on_conflict_do_nothing()
                )
        await self.shared_state.set_metadata(
            "analysis",
            artifact.analysis_key,
            {
                "artifact_id": persisted_id,
                "expires_at": artifact.expires_at.isoformat(),
                "validated": True,
            },
            ttl_seconds=self.settings.redis_metadata_ttl_seconds,
        )

    def metrics_snapshot(self) -> RetrievalMetrics:
        return RetrievalMetrics(
            decisions={
                item.value: self.metrics[item.value] for item in CacheDecision
            },
            external_calls_saved=self.metrics["external_calls_saved"],
            inflight_joins=self.metrics["inflight_joins"],
        )


class InMemoryRetrievalCoordinator:
    """Concurrency-faithful test/local implementation with the same semantics."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.snapshots: dict[str, RetrievalSnapshot] = {}
        self.inflight: dict[str, tuple[str, asyncio.Event, int]] = {}
        self.analysis: dict[str, AnalysisArtifact] = {}
        self.lock = asyncio.Lock()
        self.metrics = Counter()

    async def resolve(self, key, *, run_id: str, task_id: str) -> CacheResolution:
        del run_id, task_id
        now = datetime.now(timezone.utc)
        async with self.lock:
            current = self.snapshots.get(key.cache_key)
            if current is not None and current.expires_at > now:
                self.metrics[CacheDecision.FRESH.value] += 1
                self.metrics["external_calls_saved"] += 1
                return CacheResolution(
                    decision=CacheDecision.FRESH,
                    key_hash=key.cache_key,
                    snapshot=current,
                )
            if key.cache_key in self.inflight:
                work_id, _, generation = self.inflight[key.cache_key]
                self.metrics[CacheDecision.INFLIGHT.value] += 1
                self.metrics["inflight_joins"] += 1
                return CacheResolution(
                    decision=CacheDecision.INFLIGHT,
                    key_hash=key.cache_key,
                    work_unit_id=work_id,
                    lease_owner="in-memory",
                )
            generation = (current.generation + 1) if current else 1
            work_id = uuid4().hex
            self.inflight[key.cache_key] = (work_id, asyncio.Event(), generation)
            decision = CacheDecision.STALE if current else CacheDecision.MISS
            self.metrics[decision.value] += 1
            return CacheResolution(
                decision=decision,
                key_hash=key.cache_key,
                work_unit_id=work_id,
                lease_owner="in-memory",
                snapshot=current,
            )

    async def wait_for_snapshot(self, resolution: CacheResolution) -> RetrievalSnapshot | None:
        async with self.lock:
            inflight = self.inflight.get(resolution.key_hash)
            event = inflight[1] if inflight else None
        if event is None:
            return self.snapshots.get(resolution.key_hash)
        try:
            await asyncio.wait_for(
                event.wait(), timeout=self.settings.retrieval_join_timeout_seconds
            )
        except TimeoutError:
            return None
        self.metrics["external_calls_saved"] += 1
        return self.snapshots.get(resolution.key_hash)

    async def renew(self, resolution: CacheResolution) -> bool:
        async with self.lock:
            return resolution.key_hash in self.inflight

    async def complete(
        self,
        resolution,
        key,
        result,
        *,
        source_version,
        ttl_seconds,
        watermark=None,
    ) -> RetrievalSnapshot:
        now = datetime.now(timezone.utc)
        async with self.lock:
            work_id, event, generation = self.inflight[key.cache_key]
            snapshot = RetrievalSnapshot(
                snapshot_id=uuid4().hex,
                atomic_key=key,
                key_hash=key.cache_key,
                generation=generation,
                source_version=source_version,
                result=result,
                evidence_hash=canonical_hash(
                    [item.model_dump(mode="json") for item in result.evidence]
                ),
                watermark=watermark,
                refreshed_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds),
            )
            self.snapshots[key.cache_key] = snapshot
            self.inflight.pop(key.cache_key, None)
            event.set()
            return snapshot

    async def fail(self, resolution, error_code: str) -> None:
        del error_code
        async with self.lock:
            inflight = self.inflight.pop(resolution.key_hash, None)
            if inflight:
                inflight[1].set()

    async def get_analysis(self, analysis_key: str) -> AnalysisArtifact | None:
        artifact = self.analysis.get(analysis_key)
        if artifact and artifact.validated and artifact.expires_at > datetime.now(timezone.utc):
            by_id = {
                snapshot.snapshot_id: snapshot for snapshot in self.snapshots.values()
            }
            for snapshot_id, expected_hash in artifact.snapshot_dependencies.items():
                snapshot = by_id.get(snapshot_id)
                if snapshot is None or snapshot.evidence_hash != expected_hash:
                    return None
            return artifact
        return None

    async def put_analysis(self, artifact: AnalysisArtifact) -> None:
        if not artifact.validated:
            raise ValueError("only validated analysis artifacts may be shared")
        self.analysis[artifact.analysis_key] = artifact

    def metrics_snapshot(self) -> RetrievalMetrics:
        return RetrievalMetrics(
            decisions={item.value: self.metrics[item.value] for item in CacheDecision},
            external_calls_saved=self.metrics["external_calls_saved"],
            inflight_joins=self.metrics["inflight_joins"],
        )
