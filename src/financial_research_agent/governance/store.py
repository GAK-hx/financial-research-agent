from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from financial_research_agent.governance.models import (
    BudgetLimits,
    BudgetReservation,
    BudgetSnapshot,
    PolicyDecision,
)
from financial_research_agent.persistence.models import (
    BudgetEntryRecord,
    PolicyDecisionRecord,
    RunBudgetRecord,
)
from financial_research_agent.persistence.store import canonical_hash


class BudgetExceeded(RuntimeError):
    pass


class BudgetConflict(RuntimeError):
    pass


class GovernanceStore:
    def __init__(self, sessions: async_sessionmaker) -> None:
        self.sessions = sessions

    async def record_policy_decision(
        self,
        *,
        run_id: str,
        node_name: str,
        action: str,
        resource: str,
        allowed: bool,
        reason_code: str,
        policy_version: str,
        context: dict[str, Any],
        details: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        decision = PolicyDecision(
            decision_id=uuid4().hex,
            allowed=allowed,
            reason_code=reason_code,
            policy_version=policy_version,
            action=action,
            resource=resource,
            details=details or {},
        )
        async with self.sessions.begin() as session:
            session.add(
                PolicyDecisionRecord(
                    id=decision.decision_id,
                    run_id=run_id,
                    node_name=node_name,
                    action=action,
                    resource=resource,
                    allowed=allowed,
                    reason_code=reason_code,
                    policy_version=policy_version,
                    context_hash=canonical_hash(context),
                    details=details or {},
                )
            )
        return decision

    async def initialize_budget(
        self,
        run_id: str,
        limits: BudgetLimits,
        *,
        policy_version: str,
    ) -> BudgetSnapshot:
        payload = limits.model_dump(mode="json")
        async with self.sessions.begin() as session:
            inserted = await session.scalar(
                pg_insert(RunBudgetRecord)
                .values(
                    run_id=run_id,
                    policy_version=policy_version,
                    limits=payload,
                    reserved={},
                    committed={},
                )
                .on_conflict_do_nothing()
                .returning(RunBudgetRecord.run_id)
            )
            account = await session.get(RunBudgetRecord, run_id)
            if account is None:
                raise BudgetConflict("RUN_BUDGET_NOT_FOUND")
            if inserted is None and (
                account.limits != payload
                or account.policy_version != policy_version
            ):
                raise BudgetConflict("RUN_BUDGET_IMMUTABLE")
        return await self.snapshot(run_id)

    async def reserve(
        self,
        *,
        run_id: str,
        reservation_key: str,
        resource: str,
        amount: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> BudgetReservation:
        if amount <= 0:
            raise ValueError("budget reservation amount must be positive")
        async with self.sessions.begin() as session:
            account = await session.get(
                RunBudgetRecord, run_id, with_for_update=True
            )
            if account is None:
                raise BudgetConflict("RUN_BUDGET_NOT_INITIALIZED")
            existing = await session.scalar(
                select(BudgetEntryRecord).where(
                    BudgetEntryRecord.reservation_key == reservation_key
                )
            )
            if existing is not None:
                if (
                    existing.run_id != run_id
                    or existing.resource != resource
                    or existing.amount != amount
                ):
                    raise BudgetConflict("BUDGET_KEY_PAYLOAD_MISMATCH")
                return BudgetReservation(
                    entry_id=existing.id,
                    reservation_key=reservation_key,
                    resource=resource,
                    amount=existing.amount,
                    status=existing.status,
                    execute=existing.status == "reserved",
                )
            limit = account.limits.get(resource)
            reserved = dict(account.reserved or {})
            committed = dict(account.committed or {})
            current = reserved.get(resource, 0) + committed.get(resource, 0)
            if limit is not None and current + amount > int(limit):
                raise BudgetExceeded(
                    f"BUDGET_EXCEEDED:{resource}:limit={limit}:used={current}:requested={amount}"
                )
            entry_id = uuid4().hex
            session.add(
                BudgetEntryRecord(
                    id=entry_id,
                    run_id=run_id,
                    reservation_key=reservation_key,
                    resource=resource,
                    amount=amount,
                    status="reserved",
                    metadata_json=metadata or {},
                )
            )
            reserved[resource] = reserved.get(resource, 0) + amount
            account.reserved = reserved
            account.version += 1
            account.updated_at = func.now()
            return BudgetReservation(
                entry_id=entry_id,
                reservation_key=reservation_key,
                resource=resource,
                amount=amount,
                status="reserved",
            )

    async def commit(
        self, entry_id: str, *, actual_amount: int | None = None
    ) -> None:
        await self._settle(entry_id, "committed", actual_amount=actual_amount)

    async def release(self, entry_id: str) -> None:
        await self._settle(entry_id, "released")

    async def _settle(
        self,
        entry_id: str,
        status: str,
        *,
        actual_amount: int | None = None,
    ) -> None:
        async with self.sessions.begin() as session:
            entry = await session.get(BudgetEntryRecord, entry_id)
            if entry is None:
                raise BudgetConflict("BUDGET_ENTRY_NOT_FOUND")
            account = await session.get(
                RunBudgetRecord, entry.run_id, with_for_update=True
            )
            entry = await session.get(
                BudgetEntryRecord, entry_id, with_for_update=True
            )
            if account is None or entry is None:
                raise BudgetConflict("BUDGET_STATE_NOT_FOUND")
            if entry.status != "reserved":
                if entry.status == status:
                    return
                raise BudgetConflict(
                    f"BUDGET_ENTRY_ALREADY_{entry.status.upper()}"
                )
            settled = entry.amount if actual_amount is None else actual_amount
            if settled < 0 or settled > entry.amount:
                raise BudgetConflict("BUDGET_ACTUAL_EXCEEDS_RESERVATION")
            reserved = dict(account.reserved or {})
            committed = dict(account.committed or {})
            reserved[entry.resource] = max(
                0, reserved.get(entry.resource, 0) - entry.amount
            )
            if status == "committed":
                committed[entry.resource] = (
                    committed.get(entry.resource, 0) + settled
                )
            account.reserved = reserved
            account.committed = committed
            account.version += 1
            account.updated_at = func.now()
            entry.status = status
            entry.actual_amount = settled if status == "committed" else 0
            entry.settled_at = datetime.now(timezone.utc)

    async def snapshot(self, run_id: str) -> BudgetSnapshot:
        async with self.sessions() as session:
            account = await session.get(RunBudgetRecord, run_id)
            if account is None:
                raise BudgetConflict("RUN_BUDGET_NOT_INITIALIZED")
            open_count = await session.scalar(
                select(func.count())
                .select_from(BudgetEntryRecord)
                .where(
                    BudgetEntryRecord.run_id == run_id,
                    BudgetEntryRecord.status == "reserved",
                )
            )
        return BudgetSnapshot(
            limits=BudgetLimits.model_validate(account.limits),
            reserved=dict(account.reserved or {}),
            committed=dict(account.committed or {}),
            open_reservations=int(open_count or 0),
        )
