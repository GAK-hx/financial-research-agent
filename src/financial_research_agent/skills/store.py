from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from financial_research_agent.persistence.models import (
    RunSkillSnapshotRecord,
    SkillActivationRecord,
    SkillRecord,
    SkillReviewRecord,
    SkillVersionRecord,
)
from financial_research_agent.skills.models import (
    SkillDefinition,
    SkillSelection,
    SkillStatus,
)


class SkillLifecycleError(ValueError):
    pass


class SkillStore:
    """Persistence boundary for reviewed Skill definitions.

    Runs only read ACTIVE versions. Lifecycle transitions require an explicit
    actor and are kept separate from model execution.
    """

    def __init__(self, sessions: async_sessionmaker) -> None:
        self.sessions = sessions

    async def import_draft(
        self, definition: SkillDefinition, *, actor: str
    ) -> bool:
        if definition.status != SkillStatus.DRAFT:
            raise SkillLifecycleError("SKILL_IMPORT_REQUIRES_DRAFT")
        async with self.sessions.begin() as session:
            await session.execute(
                pg_insert(SkillRecord)
                .values(
                    id=definition.id,
                    name=definition.name,
                    skill_type=definition.skill_type.value,
                    owner=definition.owner,
                )
                .on_conflict_do_nothing()
            )
            inserted = await session.scalar(
                pg_insert(SkillVersionRecord)
                .values(
                    version_id=definition.version_id,
                    skill_id=definition.id,
                    version=definition.version,
                    status=SkillStatus.DRAFT.value,
                    checksum=definition.checksum,
                    definition=definition.model_dump(mode="json"),
                    supersedes=definition.supersedes,
                    created_by=actor,
                )
                .on_conflict_do_nothing()
                .returning(SkillVersionRecord.version_id)
            )
            if inserted is None:
                existing = await session.get(
                    SkillVersionRecord, definition.version_id
                )
                if existing is None or existing.checksum != definition.checksum:
                    raise SkillLifecycleError("SKILL_VERSION_IMMUTABLE")
                return False
        return True

    async def review(
        self, version_id: str, *, reviewer: str, notes: str = ""
    ) -> SkillDefinition:
        async with self.sessions.begin() as session:
            record = await session.get(
                SkillVersionRecord, version_id, with_for_update=True
            )
            self._require_status(record, SkillStatus.DRAFT)
            now = datetime.now(timezone.utc)
            record.status = SkillStatus.REVIEWED.value
            record.reviewed_at = now
            record.definition = {
                **record.definition,
                "status": SkillStatus.REVIEWED.value,
            }
            session.add(
                SkillReviewRecord(
                    id=uuid4().hex,
                    version_id=version_id,
                    reviewer=reviewer,
                    decision="approved",
                    notes=notes,
                )
            )
            return SkillDefinition.model_validate(record.definition)

    async def activate(
        self, version_id: str, *, actor: str, notes: str = ""
    ) -> SkillDefinition:
        async with self.sessions.begin() as session:
            record = await session.get(
                SkillVersionRecord, version_id, with_for_update=True
            )
            self._require_status(record, SkillStatus.REVIEWED)
            active = await session.scalars(
                select(SkillVersionRecord)
                .where(
                    SkillVersionRecord.skill_id == record.skill_id,
                    SkillVersionRecord.status == SkillStatus.ACTIVE.value,
                )
                .with_for_update()
            )
            now = datetime.now(timezone.utc)
            for previous in active:
                previous.status = SkillStatus.DEPRECATED.value
                previous.deprecated_at = now
                previous.definition = {
                    **previous.definition,
                    "status": SkillStatus.DEPRECATED.value,
                }
                session.add(
                    SkillActivationRecord(
                        id=uuid4().hex,
                        version_id=previous.version_id,
                        actor=actor,
                        action="deprecated_by_successor",
                        notes=f"superseded by {version_id}",
                    )
                )
            record.status = SkillStatus.ACTIVE.value
            record.activated_at = now
            record.definition = {
                **record.definition,
                "status": SkillStatus.ACTIVE.value,
            }
            session.add(
                SkillActivationRecord(
                    id=uuid4().hex,
                    version_id=version_id,
                    actor=actor,
                    action="activated",
                    notes=notes,
                )
            )
            return SkillDefinition.model_validate(record.definition)

    async def deprecate(
        self, version_id: str, *, actor: str, notes: str = ""
    ) -> SkillDefinition:
        async with self.sessions.begin() as session:
            record = await session.get(
                SkillVersionRecord, version_id, with_for_update=True
            )
            self._require_status(record, SkillStatus.ACTIVE)
            record.status = SkillStatus.DEPRECATED.value
            record.deprecated_at = datetime.now(timezone.utc)
            record.definition = {
                **record.definition,
                "status": SkillStatus.DEPRECATED.value,
            }
            session.add(
                SkillActivationRecord(
                    id=uuid4().hex,
                    version_id=version_id,
                    actor=actor,
                    action="deprecated",
                    notes=notes,
                )
            )
            return SkillDefinition.model_validate(record.definition)

    async def definitions(
        self, *, status: SkillStatus | None = None
    ) -> list[SkillDefinition]:
        statement = select(SkillVersionRecord).order_by(
            SkillVersionRecord.skill_id, SkillVersionRecord.version
        )
        if status is not None:
            statement = statement.where(SkillVersionRecord.status == status.value)
        async with self.sessions() as session:
            records = (await session.scalars(statement)).all()
        return [
            SkillDefinition.model_validate(
                {**item.definition, "status": item.status}
            )
            for item in records
        ]

    async def definition(self, version_id: str) -> SkillDefinition | None:
        async with self.sessions() as session:
            record = await session.get(SkillVersionRecord, version_id)
        if record is None:
            return None
        return SkillDefinition.model_validate(
            {**record.definition, "status": record.status}
        )

    async def bootstrap_builtins(
        self,
        definitions: Iterable[SkillDefinition],
        *,
        actor: str = "system-bootstrap",
    ) -> None:
        """Seed code-reviewed built-ins through the same audited lifecycle."""
        for definition in definitions:
            draft = definition.model_copy(update={"status": SkillStatus.DRAFT})
            created = await self.import_draft(draft, actor=actor)
            current = draft if created else await self.definition(draft.version_id)
            if current is None:
                raise SkillLifecycleError("SKILL_BOOTSTRAP_READ_FAILED")
            if current.status == SkillStatus.DEPRECATED:
                continue
            if current.status == SkillStatus.DRAFT:
                current = await self.review(
                    draft.version_id,
                    reviewer=actor,
                    notes="Built-in catalog reviewed with release.",
                )
            if current.status == SkillStatus.REVIEWED:
                await self.activate(
                    draft.version_id,
                    actor=actor,
                    notes="Built-in catalog activation.",
                )

    async def persist_run_snapshot(
        self, run_id: str, selection: SkillSelection
    ) -> None:
        payloads = [
            {
                "id": uuid4().hex,
                "run_id": run_id,
                "skill_version_id": snapshot.version_id,
                "position": position,
                "checksum": snapshot.checksum,
                "snapshot": snapshot.model_dump(mode="json"),
                "selection_reason": selection.reason,
            }
            for position, snapshot in enumerate(selection.snapshots)
        ]
        if not payloads:
            return
        async with self.sessions.begin() as session:
            for payload in payloads:
                inserted = await session.scalar(
                    pg_insert(RunSkillSnapshotRecord)
                    .values(**payload)
                    .on_conflict_do_nothing(
                        index_elements=["run_id", "skill_version_id"]
                    )
                    .returning(RunSkillSnapshotRecord.id)
                )
                if inserted is not None:
                    continue
                existing = await session.scalar(
                    select(RunSkillSnapshotRecord).where(
                        RunSkillSnapshotRecord.run_id == run_id,
                        RunSkillSnapshotRecord.skill_version_id
                        == payload["skill_version_id"],
                    )
                )
                if (
                    existing is None
                    or existing.checksum != payload["checksum"]
                    or existing.snapshot != payload["snapshot"]
                ):
                    raise SkillLifecycleError("RUN_SKILL_SNAPSHOT_IMMUTABLE")

    @staticmethod
    def _require_status(
        record: SkillVersionRecord | None, expected: SkillStatus
    ) -> None:
        if record is None:
            raise SkillLifecycleError("SKILL_VERSION_NOT_FOUND")
        if record.status != expected.value:
            raise SkillLifecycleError(
                f"INVALID_SKILL_TRANSITION:{record.status}->{expected.value}"
            )
