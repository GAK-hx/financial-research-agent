from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import numpy as np
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import (
    Evidence,
    Intent,
    QuerySpec,
    SourceReference,
    ToolName,
)
from financial_research_agent.integrations.langchain.context import (
    context_builder_runnable,
)
from financial_research_agent.integrations.langchain.skills import (
    skill_agent_context,
)
from financial_research_agent.integrations.langchain.store import (
    FinancialMemoryStore,
)
from financial_research_agent.integrations.langchain.tools import (
    build_governed_structured_tool,
)
from financial_research_agent.memory.context import ContextBuilder
from financial_research_agent.memory.models import (
    CandidateMemory,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
)
from financial_research_agent.orchestration.langgraph_runtime import (
    LangGraphResearchService,
    ResearchRuntimeContext,
    initial_research_state,
)
from financial_research_agent.rag.models import RetrievalHit
from financial_research_agent.skills.registry import SkillRegistry
from financial_research_agent.tools.report_search import (
    ReportSearchInput,
    ReportSearchTool,
)


class FakeEmbedder:
    def encode(self, texts: list[str]) -> np.ndarray:
        return np.asarray([[0.1, 0.2, 0.3] for _ in texts])


class FakeReportStore:
    def __init__(self) -> None:
        self.prepared_dimension: int | None = None

    def prepare(self, dimension: int, mode: str = "skip") -> None:
        self.prepared_dimension = dimension

    def search(
        self,
        query_vector: np.ndarray,
        stock_code: str,
        top_k: int,
        *,
        query_text: str | None = None,
        filters: dict | None = None,
    ) -> list[RetrievalHit]:
        return [
            RetrievalHit(
                chunk_id="chunk-600519-7",
                document_id="document-600519",
                stock_code=stock_code,
                stock_name="贵州茅台",
                institution="示例证券",
                report_title="贵州茅台经营质量跟踪",
                report_date=date(2026, 7, 20),
                date_unknown=False,
                page_number=7,
                source_path="/data/reports/600519.pdf",
                text="公司渠道结构保持稳定，报告认为中长期经营质量仍具韧性。",
                score=0.91,
            )
        ][:top_k]


class FakeMemoryManager:
    def __init__(self) -> None:
        self.records: dict[tuple[str, ...], MemoryRecord] = {}

    @staticmethod
    def _key(
        scope: MemoryScope,
        kind: MemoryKind,
        key: str,
    ) -> tuple[str, ...]:
        return (
            scope.tenant_id,
            scope.user_id,
            scope.session_id,
            kind.value,
            key,
        )

    async def list(
        self,
        scope: MemoryScope,
        *,
        kind: MemoryKind | None = None,
        audit_read: bool = True,
    ) -> list[MemoryRecord]:
        return [
            record
            for record in self.records.values()
            if record.scope == scope and (kind is None or record.kind == kind)
        ]

    async def write(
        self,
        scope: MemoryScope,
        candidate: CandidateMemory,
        *,
        expected_version: int | None = None,
    ) -> MemoryRecord:
        storage_key = self._key(scope, candidate.kind, candidate.key)
        previous = self.records.get(storage_key)
        now = datetime.now(UTC)
        version = previous.version + 1 if previous else 1
        record = MemoryRecord(
            memory_id=previous.memory_id if previous else uuid4().hex,
            scope=scope,
            kind=candidate.kind,
            key=candidate.key,
            value=candidate.value,
            version=version,
            status=MemoryStatus.ACTIVE,
            source=candidate.source,
            expires_at=(
                now + timedelta(seconds=candidate.ttl_seconds)
                if candidate.ttl_seconds
                else None
            ),
            created_at=previous.created_at if previous else now,
            updated_at=now,
        )
        self.records[storage_key] = record
        return record

    async def delete(
        self,
        scope: MemoryScope,
        memory_id: str,
        *,
        expected_version: int | None = None,
    ) -> MemoryRecord:
        storage_key, record = next(
            (key, value)
            for key, value in self.records.items()
            if value.scope == scope and value.memory_id == memory_id
        )
        del self.records[storage_key]
        return record


def bulk_financial_evidence() -> Evidence:
    return Evidence(
        evidence_id="financial-bulk",
        evidence_type="financial",
        subject="600519",
        statement="600519在观察期内的财务数据已完成统一口径处理。",
        data={
            "snapshot_id": 12,
            "rows": [
                {"period": f"2025-{index + 1:02d}", "revenue": index}
                for index in range(100)
            ],
        },
        source=SourceReference(
            source_type="iceberg",
            locator="iceberg://financial.metrics?snapshot_id=12",
            observed_at=datetime.now(UTC),
            metadata={"snapshot_id": 12},
        ),
    )


class LangChainEnhancementSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_retrieval_context_memory_skill_and_runtime_chain(self) -> None:
        settings = Settings(
            agent_framework="langchain",
            market_stock_codes="600519",
        )
        report_store = FakeReportStore()
        report_tool = ReportSearchTool(
            settings,
            embedder=FakeEmbedder(),
            store=report_store,
        )
        result = await report_tool.execute(
            "report-task",
            ReportSearchInput(
                stock_code="600519",
                query="经营质量与机构观点",
                top_k=1,
            ),
        )
        self.assertTrue(result.success)
        self.assertEqual(report_store.prepared_dimension, 3)
        self.assertEqual(
            result.evidence[0].source.locator,
            "milvus://research_reports_v2/chunk-600519-7",
        )
        self.assertEqual(result.evidence[0].data["institution"], "示例证券")

        async def governed(_arguments):
            return result

        structured_tool = build_governed_structured_tool(
            report_tool,
            governed,
        )
        message = await structured_tool.ainvoke(
            {
                "type": "tool_call",
                "id": "report-call",
                "name": "report_search",
                "args": {
                    "stock_code": "600519",
                    "query": "经营质量与机构观点",
                    "top_k": 1,
                },
            }
        )
        self.assertIsInstance(message, ToolMessage)
        document = message.artifact["documents"][0]
        self.assertEqual(document["metadata"]["page_number"], 7)
        self.assertEqual(
            document["metadata"]["source_locator"],
            result.evidence[0].source.locator,
        )

        query = QuerySpec(
            stock_codes=["600519"],
            start_date=date(2025, 1, 1),
            end_date=date(2026, 7, 28),
            intent=Intent.REPORT,
            dimensions=["risk"],
        )
        selection = SkillRegistry.from_builtin_catalog().select(
            query,
            {item.value for item in ToolName},
        )
        agent_context = skill_agent_context(selection)
        self.assertIn("report_search", agent_context["allowed_tool_names"])
        self.assertEqual(
            agent_context["required_evidence"][0]["evidence_type"],
            "research_report",
        )

        context = await context_builder_runnable(
            ContextBuilder(policy_version="smoke-policy"),
            "build_report",
        ).ainvoke(
            {
                "run_id": "enhancement-smoke",
                "node_name": "generate_report",
                "query": query,
                "evidence": [
                    result.evidence[0],
                    bulk_financial_evidence(),
                ],
                "selection": selection,
                "memory": [],
            }
        )
        compact_rows = context.payload["evidence"][1]["data"]["rows"]
        self.assertTrue(compact_rows["omitted_from_model_context"])
        self.assertEqual(compact_rows["row_count"], 100)
        self.assertTrue(context.manifest.evidence_protection_passed)
        self.assertLess(
            context.manifest.token_estimate_after,
            context.manifest.token_estimate_before,
        )

        manager = FakeMemoryManager()
        memory_store = FinancialMemoryStore(manager)
        scope = MemoryScope(
            tenant_id="tenant-a",
            user_id="user-a",
            session_id="session-a",
        )
        namespace = memory_store.namespace(scope, MemoryKind.SESSION)
        await memory_store.aput(
            namespace,
            "last_stock_codes",
            {
                "value": ["600519"],
                "ttl_seconds": 3600,
                "source": {
                    "source_type": "api",
                    "source_id": "smoke",
                },
            },
        )
        stored = await memory_store.aget(namespace, "last_stock_codes")
        self.assertEqual(stored.value["value"], ["600519"])
        self.assertIsNotNone(
            manager.records[
                (
                    "tenant-a",
                    "user-a",
                    "session-a",
                    "session",
                    "last_stock_codes",
                )
            ].expires_at
        )
        isolated = await memory_store.aget(
            memory_store.namespace(
                scope.model_copy(update={"tenant_id": "tenant-b"}),
                MemoryKind.SESSION,
            ),
            "last_stock_codes",
        )
        self.assertIsNone(isolated)

        state = initial_research_state(
            "分析贵州茅台",
            "runtime-smoke",
            tenant_id="tenant-a",
            user_id="user-a",
            session_id="session-a",
        )
        runtime = Runtime(
            context=ResearchRuntimeContext(
                tenant_id="tenant-a",
                user_id="user-a",
                session_id="session-a",
                run_id="runtime-smoke",
            ),
            store=memory_store,
        )
        LangGraphResearchService._validate_runtime_scope(state, runtime)
        with self.assertRaisesRegex(
            PermissionError,
            "RUNTIME_CONTEXT_SCOPE_MISMATCH",
        ):
            LangGraphResearchService._validate_runtime_scope(
                state,
                Runtime(
                    context=ResearchRuntimeContext(
                        tenant_id="tenant-b",
                        user_id="user-a",
                        session_id="session-a",
                        run_id="runtime-smoke",
                    )
                ),
            )


if __name__ == "__main__":
    unittest.main()
