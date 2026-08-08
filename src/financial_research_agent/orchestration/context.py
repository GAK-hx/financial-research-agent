from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field

from financial_research_agent.domain.models import (
    AnalysisPlan,
    Evidence,
    ExecutionMetadata,
    QuerySpec,
    SemanticAlignmentResult,
    ToolResult,
)
from financial_research_agent.governance.models import (
    BudgetSnapshot,
    CompletionResult,
)
from financial_research_agent.memory.models import ContextManifest, MemoryScope
from financial_research_agent.orchestration.evidence_builder import EvidenceBuilder


class RunStage(StrEnum):
    CREATED = "created"
    LOADING_MEMORY = "loading_memory"
    INTERPRETING = "interpreting"
    ALIGNING_SEMANTICS = "aligning_semantics"
    REMEMBERING = "remembering"
    SELECTING_SKILL = "selecting_skill"
    INITIALIZING_GOVERNANCE = "initializing_governance"
    PLANNING = "planning"
    VALIDATING_PLAN = "validating_plan"
    EXECUTING = "executing"
    BUILDING_EVIDENCE = "building_evidence"
    CHECKING_EVIDENCE = "checking_evidence"
    REPLANNING = "replanning"
    COMPLETING = "completing"
    COMPLETED = "completed"
    FAILED = "failed"


class StageTiming(BaseModel):
    stage: RunStage
    duration_ms: int = Field(ge=0)


class WorkingMemory(BaseModel):
    run_id: str
    question: str
    query: QuerySpec | None = None
    plan: AnalysisPlan | None = None
    completed_tasks: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class RunContext(BaseModel):
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    question: str
    stage: RunStage = RunStage.CREATED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    query: QuerySpec | None = None
    semantic_alignment: SemanticAlignmentResult | None = None
    plan: AnalysisPlan | None = None
    planner_source: str | None = None
    tool_results: list[ToolResult] = Field(default_factory=list)
    evidence_memory: list[Evidence] = Field(default_factory=list)
    timings: list[StageTiming] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    def build_working_memory(self) -> WorkingMemory:
        return WorkingMemory(
            run_id=self.run_id,
            question=self.question,
            query=self.query,
            plan=self.plan,
            completed_tasks=[result.task_id for result in self.tool_results],
            evidence_ids=[evidence.evidence_id for evidence in self.evidence_memory],
        )

    def collect_evidence(self, max_evidence: int) -> None:
        self.evidence_memory = EvidenceBuilder().build(
            self.run_id, self.tool_results, max_evidence
        )


class OrchestrationResult(BaseModel):
    run_id: str
    success: bool
    stage: RunStage
    query: QuerySpec | None
    plan: AnalysisPlan | None
    planner_source: str | None
    tool_results: list[ToolResult]
    evidence: list[Evidence]
    timings: list[StageTiming]
    errors: list[str]
    selected_skills: list[str] = Field(default_factory=list)
    skill_selection_reason: str | None = None
    policy_version: str | None = None
    budget: BudgetSnapshot | None = None
    completion: CompletionResult | None = None
    memory_scope: MemoryScope | None = None
    memory_warnings: list[str] = Field(default_factory=list)
    context_manifests: dict[str, ContextManifest] = Field(default_factory=dict)
    semantic_alignment: SemanticAlignmentResult | None = None
    execution_metadata: ExecutionMetadata | None = None
