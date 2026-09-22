from __future__ import annotations

import os
import unittest
from datetime import date
from uuid import uuid4

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import Intent, QuerySpec, ToolName
from financial_research_agent.skills.models import (
    SkillDefinition,
    SkillStatus,
)
from financial_research_agent.skills.registry import SkillConflict, SkillRegistry

try:
    from sqlalchemy import delete

    from financial_research_agent.persistence.database import (
        create_business_engine,
        create_session_factory,
    )
    from financial_research_agent.persistence.models import RunRecord, SkillRecord
    from financial_research_agent.persistence.store import BusinessStore
    from financial_research_agent.skills.store import SkillLifecycleError, SkillStore

    PERSISTENCE_AVAILABLE = True
except ModuleNotFoundError:
    PERSISTENCE_AVAILABLE = False


POSTGRES_TESTS = (
    PERSISTENCE_AVAILABLE
    and os.environ.get("RUN_POSTGRES_TESTS", "").lower() in {"1", "true", "yes"}
)


def query(
    intent: Intent = Intent.FINANCIAL, dimensions: list[str] | None = None
) -> QuerySpec:
    return QuerySpec(
        stock_codes=["600519"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        intent=intent,
        dimensions=dimensions or [],
    )


class SkillRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = SkillRegistry.from_builtin_catalog()
        self.available = {item.value for item in ToolName}

    def test_builtin_catalog_is_versioned_and_content_checksum_ignores_status(self):
        definitions = self.registry.versions()
        self.assertEqual(len(definitions), 13)
        active = definitions[0]
        draft = active.model_copy(update={"status": SkillStatus.DRAFT})
        self.assertEqual(active.checksum, draft.checksum)
        self.assertRegex(active.version_id, r"^[a-z0-9_]+@\d+\.\d+\.\d+$")

    def test_only_active_matching_skill_is_selected(self):
        active = self.registry.get("financial_growth_analysis@1.1.0")
        draft = active.model_copy(
            update={"version": "1.1.0", "status": SkillStatus.DRAFT}
        )
        registry = SkillRegistry([draft])
        selection = registry.select(
            query(dimensions=["financial_growth"]), self.available
        )
        self.assertEqual(selection.snapshots, [])
        with self.assertRaises(ValueError):
            registry.get(draft.version_id)

    def test_composition_only_reduces_tools_and_uses_stricter_budget(self):
        growth = self.registry.get("financial_growth_analysis@1.1.0")
        concise = self.registry.get("concise_research_report@1.1.0")
        selection = self.registry.compose([growth, concise], self.available)
        self.assertEqual(
            {item.value for item in selection.effective_allowed_tools},
            {
                "financial_query",
                "report_candidate_search",
                "report_content_search",
            },
        )
        self.assertEqual(selection.workflow_constraints.max_tool_calls, 2)
        self.assertTrue(
            {item.value for item in selection.effective_allowed_tools}
            <= self.available
        )

    def test_conflict_and_missing_evidence_are_deterministically_rejected(self):
        concise = self.registry.get("concise_research_report@1.1.0")
        risk = self.registry.get("risk_focused_report@1.1.0")
        with self.assertRaisesRegex(SkillConflict, "SKILL_CONFLICT"):
            self.registry.compose([concise, risk], self.available)

        selection = self.registry.select(
            query(dimensions=["financial_growth"]), self.available
        )
        self.assertEqual(
            self.registry.validate_evidence(selection, []),
            ["SKILL_EVIDENCE_MISSING:financial:required=1:actual=0"],
        )
        self.assertEqual(
            self.registry.validate_evidence(selection, ["financial"]), []
        )

    def test_plan_cannot_use_tool_or_calls_outside_skill_snapshot(self):
        selection = self.registry.select(
            query(dimensions=["financial_growth"]), self.available
        )
        self.registry.validate_plan(selection, ["financial_query"])
        with self.assertRaisesRegex(ValueError, "SKILL_TOOL_FORBIDDEN"):
            self.registry.validate_plan(selection, ["market_query"])
        with self.assertRaisesRegex(ValueError, "SKILL_TOOL_BUDGET_EXCEEDED"):
            self.registry.validate_plan(
                selection,
                ["financial_query", "financial_query", "financial_query"],
            )

    def test_comprehensive_evidence_follows_explicit_analysis_domains(self):
        comprehensive = query(intent=Intent.COMPREHENSIVE).model_copy(
            update={"analysis_domains": ["market", "financial"]}
        )
        selection = self.registry.select(comprehensive, self.available)
        self.assertEqual(
            {
                item.evidence_type
                for item in selection.required_evidence
            },
            {"market", "indicator", "financial"},
        )
        self.assertNotIn(
            "research_report",
            {
                item.evidence_type
                for item in selection.required_evidence
            },
        )

    def test_report_profiles_do_not_reduce_research_tool_permissions(self):
        concise = self.registry.select(
            query(intent=Intent.MARKET, dimensions=["concise"]), self.available
        )
        self.assertEqual(concise.selected_ids, ["market_trend_analysis@1.0.0"])
        self.assertEqual([item.id for item in concise.report_profiles], ["concise"])
        combined = self.registry.select(
            query(intent=Intent.MARKET, dimensions=["concise", "risk"]),
            self.available,
        )
        self.assertEqual(
            [item.id for item in combined.report_profiles], ["concise", "risk"]
        )


@unittest.skipUnless(
    POSTGRES_TESTS, "Set RUN_POSTGRES_TESTS=1 for PostgreSQL Skill integration"
)
class SkillStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.settings = Settings(
            business_database_url=os.environ["BUSINESS_DATABASE_URL"]
        )
        self.engine = create_business_engine(self.settings)
        self.sessions = create_session_factory(self.engine)
        self.store = SkillStore(self.sessions)
        self.skill_id = f"test_skill_{uuid4().hex[:12]}"
        self.run_id = f"skill-run-{uuid4().hex}"

    async def asyncTearDown(self) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                delete(RunRecord).where(RunRecord.id == self.run_id)
            )
            await session.execute(
                delete(SkillRecord).where(SkillRecord.id == self.skill_id)
            )
        await self.engine.dispose()

    def definition(self) -> SkillDefinition:
        source = SkillRegistry.from_builtin_catalog().get(
            "financial_growth_analysis@1.1.0"
        )
        payload = source.model_dump(mode="json", exclude={"checksum"})
        payload.update(
            {
                "id": self.skill_id,
                "name": "测试财务分析",
                "version": "1.0.0",
                "status": SkillStatus.DRAFT.value,
            }
        )
        return SkillDefinition.model_validate(payload)

    async def test_lifecycle_requires_review_and_run_snapshot_is_immutable(self):
        definition = self.definition()
        self.assertTrue(await self.store.import_draft(definition, actor="tester"))
        with self.assertRaises(SkillLifecycleError):
            await self.store.activate(definition.version_id, actor="tester")
        await self.store.review(
            definition.version_id, reviewer="reviewer", notes="checked"
        )
        active = await self.store.activate(
            definition.version_id, actor="publisher", notes="release"
        )
        self.assertEqual(active.status, SkillStatus.ACTIVE)

        business = BusinessStore(self.engine, self.sessions)
        await business.create_run(
            self.run_id, self.run_id, "skill snapshot", "langgraph"
        )
        selection = SkillRegistry([active]).select(
            query(dimensions=["financial_growth"]),
            {item.value for item in ToolName},
        )
        await self.store.persist_run_snapshot(self.run_id, selection)
        await self.store.persist_run_snapshot(self.run_id, selection)

        broken = selection.model_copy(deep=True)
        broken.snapshots[0].checksum = "0" * 64
        with self.assertRaises(SkillLifecycleError):
            await self.store.persist_run_snapshot(self.run_id, broken)
