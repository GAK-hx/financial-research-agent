from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from typing import Any

from langgraph.store.base import (
    BaseStore,
    GetOp,
    Item,
    ListNamespacesOp,
    Op,
    PutOp,
    Result,
    SearchItem,
    SearchOp,
)

from financial_research_agent.memory.manager import MemoryManager
from financial_research_agent.memory.models import (
    CandidateMemory,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySource,
)

NAMESPACE_PREFIX = "financial_agent"


class FinancialMemoryStore(BaseStore):
    """LangGraph Store interface preserving MemoryManager governance."""

    supports_ttl = False

    def __init__(self, manager: MemoryManager) -> None:
        self.manager = manager

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.abatch(ops))
        raise RuntimeError("use abatch from asynchronous graph execution")

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        results: list[Result] = []
        for operation in ops:
            if isinstance(operation, GetOp):
                results.append(await self._get(operation))
            elif isinstance(operation, PutOp):
                await self._put(operation)
                results.append(None)
            elif isinstance(operation, SearchOp):
                results.append(await self._search(operation))
            elif isinstance(operation, ListNamespacesOp):
                # Deliberately disabled: enumerating tenant/user namespaces would
                # violate the isolation boundary enforced by MemoryManager.
                results.append([])
            else:
                raise TypeError(
                    f"unsupported LangGraph store operation: "
                    f"{type(operation).__name__}"
                )
        return results

    async def _get(self, operation: GetOp) -> Item | None:
        scope, kind = self._parse_namespace(operation.namespace)
        records = await self.manager.list(scope, kind=kind)
        record = next(
            (item for item in records if item.key == operation.key),
            None,
        )
        return self._item(operation.namespace, record) if record else None

    async def _put(self, operation: PutOp) -> None:
        scope, kind = self._parse_namespace(operation.namespace)
        records = await self.manager.list(scope, kind=kind)
        existing = next(
            (item for item in records if item.key == operation.key),
            None,
        )
        if operation.value is None:
            if existing is not None:
                await self.manager.delete(
                    scope,
                    existing.memory_id,
                    expected_version=existing.version,
                )
            return
        payload = dict(operation.value)
        source_payload = payload.get("source") or {}
        candidate = CandidateMemory(
            kind=kind,
            key=operation.key,
            value=payload.get("value"),
            source=MemorySource(
                source_type=source_payload.get("source_type", "api"),
                source_id=source_payload.get(
                    "source_id", f"langgraph-store:{operation.key}"
                ),
                run_id=source_payload.get("run_id"),
                metadata={
                    **(source_payload.get("metadata") or {}),
                    "adapter": "langgraph_store",
                },
            ),
            ttl_seconds=payload.get("ttl_seconds"),
            explicitly_confirmed=bool(
                payload.get("explicitly_confirmed", False)
            ),
        )
        await self.manager.write(
            scope,
            candidate,
            expected_version=existing.version if existing else None,
        )

    async def _search(self, operation: SearchOp) -> list[SearchItem]:
        scope, kind = self._parse_namespace(operation.namespace_prefix)
        records = await self.manager.list(scope, kind=kind)
        query = (operation.query or "").casefold()
        filtered = [
            record
            for record in records
            if not query
            or query
            in json.dumps(
                record.value,
                ensure_ascii=False,
                default=str,
            ).casefold()
        ]
        selected = filtered[
            operation.offset : operation.offset + operation.limit
        ]
        return [
            SearchItem(
                namespace=operation.namespace_prefix,
                key=record.key,
                value=self._value(record),
                created_at=record.created_at,
                updated_at=record.updated_at,
                score=None,
            )
            for record in selected
        ]

    @staticmethod
    def namespace(
        scope: MemoryScope,
        kind: MemoryKind,
    ) -> tuple[str, ...]:
        return (
            NAMESPACE_PREFIX,
            scope.tenant_id,
            scope.user_id,
            scope.session_id,
            kind.value,
        )

    @staticmethod
    def _parse_namespace(
        namespace: tuple[str, ...],
    ) -> tuple[MemoryScope, MemoryKind]:
        if len(namespace) != 5 or namespace[0] != NAMESPACE_PREFIX:
            raise ValueError("invalid financial memory namespace")
        return (
            MemoryScope(
                tenant_id=namespace[1],
                user_id=namespace[2],
                session_id=namespace[3],
            ),
            MemoryKind(namespace[4]),
        )

    @classmethod
    def _item(
        cls,
        namespace: tuple[str, ...],
        record: MemoryRecord,
    ) -> Item:
        return Item(
            namespace=namespace,
            key=record.key,
            value=cls._value(record),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _value(record: MemoryRecord) -> dict[str, Any]:
        return {
            "value": record.value,
            "kind": record.kind.value,
            "version": record.version,
            "status": record.status.value,
            "source": record.source.model_dump(mode="json"),
            "expires_at": (
                record.expires_at.isoformat()
                if record.expires_at is not None
                else None
            ),
        }
