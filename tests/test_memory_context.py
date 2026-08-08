from __future__ import annotations

import os
import unittest
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from financial_research_agent.domain.models import (
    Evidence,
    Intent,
    QuerySpec,
    SourceReference,
)
from financial_research_agent.memory.context import (
    ContextBuilder,
    ContextPolicy,
    EvidenceProtectionError,
    EvidenceProtector,
    evidence_context_item,
)
from financial_research_agent.memory.manager import (
    MemoryConflict,
    MemoryManager,
    MemoryNotFound,
    MemoryRejected,
)
from financial_research_agent.memory.models import (
    CandidateMemory,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemorySource,
    MemoryStatus,
)
from financial_research_agent.skills.registry import SkillRegistry

try:
    from sqlalchemy import delete, select, update

    from financial_research_agent.persistence.database import (
        create_business_engine,
        create_session_factory,
    )
    from financial_research_agent.persistence.models import (
        MemoryAuditRecord,
        MemoryRecordModel,
        MemoryVersionRecord,
    )

    PERSISTENCE_AVAILABLE = True
except ModuleNotFoundError:
    PERSISTENCE_AVAILABLE = False

from financial_research_agent.config import Settings


POSTGRES_TESTS = (
    PERSISTENCE_AVAILABLE
    and os.environ.get("RUN_POSTGRES_TESTS", "").lower() in {"1", "true", "yes"}
)


def source(source_id: str = "test") -> MemorySource:
    return MemorySource(
        source_type="explicit_user_confirmation",
        source_id=source_id,
    )


def memory_record(
    *,
    kind: MemoryKind,
    key: str,
    value,
    memory_id: str = "memory-1",
) -> MemoryRecord:
    now = datetime.now(timezone.utc)
    return MemoryRecord(
        memory_id=memory_id,
        scope=MemoryScope(),
        kind=kind,
        key=key,
        value=value,
        version=1,
        status=MemoryStatus.ACTIVE,
        source=source(),
        created_at=now,
        updated_at=now,
    )


def financial_evidence(*, rows: int = 100) -> Evidence:
    return Evidence(
        evidence_id="run:financial-1",
        evidence_type="financial",
        subject="600519",
        statement="600519最新营业收入为100亿元，报告期为2025年。",
        data={
            "snapshot_id": 12,
            "formula_version": "financial_metrics_v1",
            "data_as_of": "2025-12-31",
            "rows": [
                {"period": f"2025-{index + 1:02d}", "revenue": index * 10}
                for index in range(rows)
            ],
        },
        source=SourceReference(
            source_type="iceberg",
            locator="iceberg://financial.metrics?snapshot_id=12",
            observed_at=datetime.now(timezone.utc),
            metadata={"snapshot_id": 12, "table": "financial.metrics"},
        ),
    )


class ContextBuilderTests(unittest.IsolatedAsyncioTestCase):
    async def test_bulk_rows_are_compressed_but_protected_facts_are_identical(self):
        evidence = financial_evidence(rows=100)
        query = QuerySpec(
            stock_codes=["600519"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            intent=Intent.FINANCIAL,
            dimensions=[],
        )
        selection = SkillRegistry.from_builtin_catalog().select(
            query, {"financial_query", "report_search"}
        )
        built = await ContextBuilder(
            policy_version="test-policy"
        ).build_report(
            run_id="context-run",
            node_name="generate_report",
            query=query,
            evidence=[evidence],
            selection=selection,
            memory=[],
        )
        item = built.payload["evidence"][0]
        self.assertTrue(item["data"]["rows"]["omitted_from_model_context"])
        self.assertEqual(item["data"]["rows"]["row_count"], 100)
        self.assertLess(
            built.manifest.token_estimate_after,
            built.manifest.token_estimate_before,
        )
        self.assertTrue(built.manifest.evidence_protection_passed)
        self.assertEqual(
            built.manifest.evidence_protection_hash,
            EvidenceProtector.hash([item]),
        )

    async def test_small_analytical_rows_remain_in_report_context(self):
        evidence = financial_evidence(rows=5)
        query = QuerySpec(
            stock_codes=["600519"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            intent=Intent.FINANCIAL,
            dimensions=[],
        )
        selection = SkillRegistry.from_builtin_catalog().select(
            query, {"financial_query"}
        )

        built = await ContextBuilder(policy_version="test-policy").build_report(
            run_id="small-rows-run",
            node_name="generate_report",
            query=query,
            evidence=[evidence],
            selection=selection,
            memory=[],
        )

        self.assertEqual(len(built.payload["evidence"][0]["data"]["rows"]), 5)

    def test_evidence_locator_or_statement_change_is_rejected(self):
        original = [evidence_context_item(financial_evidence())]
        changed = [dict(original[0])]
        changed[0]["source"] = {
            **original[0]["source"],
            "locator": "iceberg://forged",
        }
        with self.assertRaises(EvidenceProtectionError):
            EvidenceProtector.validate(original, changed)

    async def test_one_layer_summary_cannot_introduce_numbers(self):
        async def bad_summary(run_id, node_name, payload):
            return {"summary": "新增数字999"}

        policy = ContextPolicy(
            policy_id="interpret_summary_test",
            node_name="interpret",
            max_input_tokens=256,
            reserved_output_tokens=0,
            max_session_items=32,
            allow_model_summary=True,
        )
        builder = ContextBuilder(
            policy_version="test",
            policies={"interpret": policy},
            model_summary_enabled=True,
            summarizer=bad_summary,
        )
        long_memory = [
            memory_record(
                kind=MemoryKind.SESSION,
                key="last_stock_codes",
                value=["这是很长的非数字上下文" * 100],
                memory_id=f"memory-{index}",
            )
            for index in range(10)
        ]
        with self.assertRaisesRegex(
            EvidenceProtectionError, "INTRODUCED_NUMBER"
        ):
            await builder.build_interpret(
                run_id="summary-run",
                question="继续分析",
                memory=long_memory,
            )

    async def test_context_manifest_records_episodic_and_knowledge_lineage(self):
        episodic = memory_record(
            kind=MemoryKind.EPISODIC,
            key="episode_run1",
            value={"historical_only": True, "summary": "历史验证结果"},
        ).model_copy(
            update={
                "source": MemorySource(
                    source_type="validated_run",
                    source_id="run1",
                    run_id="run1",
                    metadata={"validation_passed": True},
                )
            }
        )
        query = QuerySpec(
            stock_codes=["600519"],
            intent=Intent.REPORT,
            dimensions=[],
        )
        selection = SkillRegistry.from_builtin_catalog().select(
            query, {"report_search"}
        )
        built = await ContextBuilder(policy_version="test").build_plan(
            run_id="lineage-run",
            question="分析事件",
            query=query,
            selection=selection,
            tool_schemas=[],
            budget=None,
            memory=[episodic],
            knowledge=[
                {
                    "event_id": "event-1",
                    "source_url": "https://example.invalid/event-1",
                    "extraction_version": "event_extraction_v1",
                    "content": "经过校验的事件知识",
                }
            ],
        )
        refs = {item.item_type: item for item in built.manifest.included}
        self.assertEqual(
            refs["knowledge"].source_locator,
            "https://example.invalid/event-1",
        )
        self.assertEqual(refs["knowledge"].version, "event_extraction_v1")
        self.assertIn("OUTPUT_TOKENS_RESERVED", built.manifest.warnings[0])

    def test_preference_candidate_requires_explicit_confirmation(self):
        with self.assertRaises(ValueError):
            CandidateMemory(
                kind=MemoryKind.PREFERENCE,
                key="output_length",
                value="concise",
                source=source(),
            )

    def test_episodic_candidate_requires_validated_run(self):
        with self.assertRaises(ValueError):
            CandidateMemory(
                kind=MemoryKind.EPISODIC,
                key="episode_unverified",
                value={"summary": "unverified"},
                source=MemorySource(
                    source_type="validated_run",
                    source_id="run-unverified",
                ),
            )


@unittest.skipUnless(
    POSTGRES_TESTS, "Set RUN_POSTGRES_TESTS=1 for PostgreSQL memory integration"
)
class MemoryManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.settings = Settings(
            business_database_url=os.environ["BUSINESS_DATABASE_URL"]
        )
        self.engine = create_business_engine(self.settings)
        self.sessions = create_session_factory(self.engine)
        self.manager = MemoryManager(
            self.sessions, session_ttl_seconds=3600
        )
        suffix = uuid4().hex[:10]
        self.scope = MemoryScope(
            tenant_id=f"tenant-{suffix}",
            user_id=f"user-{suffix}",
            session_id=f"session-{suffix}",
        )

    async def asyncTearDown(self) -> None:
        async with self.sessions.begin() as session:
            memory_ids = list(
                await session.scalars(
                    select(MemoryRecordModel.id).where(
                        MemoryRecordModel.tenant_id == self.scope.tenant_id
                    )
                )
            )
            if memory_ids:
                await session.execute(
                    delete(MemoryVersionRecord).where(
                        MemoryVersionRecord.memory_id.in_(memory_ids)
                    )
                )
            await session.execute(
                delete(MemoryAuditRecord).where(
                    MemoryAuditRecord.tenant_id == self.scope.tenant_id
                )
            )
            await session.execute(
                delete(MemoryRecordModel).where(
                    MemoryRecordModel.tenant_id == self.scope.tenant_id
                )
            )
        await self.engine.dispose()

    async def test_scope_isolation_preference_confirmation_and_delete(self):
        session_record = await self.manager.write(
            self.scope,
            CandidateMemory(
                kind=MemoryKind.SESSION,
                key="last_stock_codes",
                value=["600519"],
                source=MemorySource(
                    source_type="query_spec", source_id="run-1"
                ),
            ),
        )
        preference = await self.manager.write(
            self.scope,
            CandidateMemory(
                kind=MemoryKind.PREFERENCE,
                key="output_length",
                value="concise",
                source=source(),
                explicitly_confirmed=True,
            ),
        )
        other_session = self.scope.model_copy(
            update={"session_id": "another-session"}
        )
        visible = await self.manager.list(other_session)
        self.assertEqual([item.memory_id for item in visible], [preference.memory_id])
        other_user = self.scope.model_copy(update={"user_id": "another-user"})
        self.assertEqual(await self.manager.list(other_user), [])
        with self.assertRaises(MemoryNotFound):
            await self.manager.delete(other_user, session_record.memory_id)
        deleted = await self.manager.delete(
            self.scope,
            session_record.memory_id,
            expected_version=session_record.version,
        )
        self.assertEqual(deleted.status, MemoryStatus.DELETED)
        with self.assertRaises(MemoryConflict):
            await self.manager.write(
                self.scope,
                CandidateMemory(
                    kind=MemoryKind.SESSION,
                    key="last_stock_codes",
                    value=["300750"],
                    source=MemorySource(
                        source_type="query_spec", source_id="run-2"
                    ),
                ),
                expected_version=1,
            )

    async def test_sensitive_memory_is_rejected_and_ttl_expires(self):
        with self.assertRaisesRegex(
            MemoryRejected, "SENSITIVE_CONTENT"
        ):
            await self.manager.write(
                self.scope,
                CandidateMemory(
                    kind=MemoryKind.PREFERENCE,
                    key="output_length",
                    value="password=sk-secret-value-123456",
                    source=source(),
                    explicitly_confirmed=True,
                ),
            )
        record = await self.manager.write(
            self.scope,
            CandidateMemory(
                kind=MemoryKind.SESSION,
                key="last_stock_codes",
                value=["600519"],
                source=MemorySource(
                    source_type="query_spec", source_id="run-ttl"
                ),
            ),
        )
        async with self.sessions.begin() as session:
            await session.execute(
                update(MemoryRecordModel)
                .where(MemoryRecordModel.id == record.memory_id)
                .values(
                    expires_at=datetime.now(timezone.utc)
                    - timedelta(seconds=1)
                )
            )
        self.assertEqual(await self.manager.expire_due(scope=self.scope), 1)
        self.assertEqual(await self.manager.list(self.scope), [])

    async def test_query_memory_resolves_same_session_follow_up_only(self):
        query = QuerySpec(
            stock_codes=["600519"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            intent=Intent.FINANCIAL,
            dimensions=[],
        )
        await self.manager.remember_query(
            self.scope, query, run_id="query-run"
        )
        records = await self.manager.list(self.scope)
        resolved, warnings = self.manager.resolve_question(
            "继续分析它最近一年的表现", records
        )
        self.assertIn("600519", resolved)
        self.assertTrue(warnings)
        other = self.scope.model_copy(update={"session_id": "other-session"})
        unresolved, warnings = self.manager.resolve_question(
            "继续分析它最近一年的表现",
            await self.manager.list(other),
        )
        self.assertNotIn("600519", unresolved)
        self.assertEqual(warnings, [])

    async def test_validated_reflection_is_versioned_and_idempotent(self):
        reflected = await self.manager.reflect(
            self.scope,
            run_id="verified-run-1",
            task_type="report",
            payload={"summary": "已验证历史结果"},
            validation_passed=True,
            skill_versions=["research_report_review@1.0.0"],
            model_version="deepseek-v4-flash",
        )
        repeated = await self.manager.reflect(
            self.scope,
            run_id="verified-run-1",
            task_type="report",
            payload={"summary": "已验证历史结果"},
            validation_passed=True,
            skill_versions=["research_report_review@1.0.0"],
            model_version="deepseek-v4-flash",
        )
        self.assertEqual(repeated.version, reflected.version)
        versions = await self.manager.versions(self.scope, reflected.memory_id)
        self.assertEqual([item.version for item in versions], [1])

    async def test_memory_api_requires_confirmation_and_enforces_scope(self):
        import httpx

        from financial_research_agent.api import create_app

        app = create_app()
        app.state.settings = self.settings.model_copy(
            update={
                "memory_enabled": True,
                "identity_mode": "api_key",
                "agent_api_key": "memory-test-key",
            }
        )
        headers = {
            "Authorization": "Bearer memory-test-key",
            "X-Tenant-ID": self.scope.tenant_id,
            "X-User-ID": self.scope.user_id,
            "X-Agent-Role": "researcher",
        }
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            rejected = await client.post(
                "/memory/preferences",
                json={
                    "scope": self.scope.model_dump(),
                    "key": "output_length",
                    "value": "concise",
                    "explicitly_confirmed": False,
                },
                headers=headers,
            )
            self.assertEqual(rejected.status_code, 422)
            created = await client.post(
                "/memory/preferences",
                json={
                    "scope": self.scope.model_dump(),
                    "key": "output_length",
                    "value": "concise",
                    "explicitly_confirmed": True,
                },
                headers=headers,
            )
            self.assertEqual(created.status_code, 200)
            memory_id = created.json()["memory_id"]
            listed = await client.get(
                "/memory",
                params={
                    "tenant_id": self.scope.tenant_id,
                    "user_id": self.scope.user_id,
                    "session_id": "another-session",
                },
                headers=headers,
            )
            self.assertEqual(
                [item["memory_id"] for item in listed.json()["records"]],
                [memory_id],
            )
            hidden = await client.get(
                "/memory",
                params={
                    "tenant_id": self.scope.tenant_id,
                    "user_id": "another-user",
                    "session_id": self.scope.session_id,
                },
                headers={**headers, "X-User-ID": "another-user"},
            )
            self.assertEqual(hidden.json()["records"], [])
            deleted = await client.request(
                "DELETE",
                f"/memory/{memory_id}",
                json={"scope": self.scope.model_dump()},
                headers=headers,
            )
            self.assertEqual(deleted.status_code, 200)


if __name__ == "__main__":
    unittest.main()
