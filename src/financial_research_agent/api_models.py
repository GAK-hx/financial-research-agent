from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from financial_research_agent.domain.models import (
    AnalysisPlan,
    Evidence,
    ExecutionMetadata,
    QuerySpec,
    ResearchReport,
    SemanticAlignmentResult,
    ValidationResult,
)
from financial_research_agent.governance.models import (
    BudgetSnapshot,
    CompletionResult,
)
from financial_research_agent.memory.models import (
    CandidateMemory,
    ContextManifest,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemoryVersion,
)
from financial_research_agent.jobs.models import JobEvent, JobSnapshot


class ApiError(BaseModel):
    code: str
    message: str
    run_id: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ApiError


class ToolStatus(BaseModel):
    task_id: str
    tool_name: str
    success: bool
    error_code: str | None
    error_message: str | None
    latency_ms: int
    evidence_count: int


class RuntimeMetadata(BaseModel):
    model_provider: str
    model_name: str | None
    planner_prompt_version: str
    report_prompt_version: str
    tool_versions: dict[str, str]
    gateway_version: str | None = None
    policy_version: str | None = None
    model_context_window_tokens: int | None = None
    model_max_output_tokens: int | None = None
    model_thinking_mode: str | None = None


class AnalyzeResponse(BaseModel):
    success: bool
    run_id: str
    planner_source: str | None
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
    reporting_status: str | None
    query_spec: QuerySpec | None
    plan: AnalysisPlan | None
    tool_status: list[ToolStatus]
    evidence: list[Evidence]
    report: ResearchReport | None
    validation: ValidationResult | None
    timings: dict[str, int]
    metadata: RuntimeMetadata
    error: ApiError | None = None


class HealthComponent(BaseModel):
    status: str
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    model_configured: bool
    components: dict[str, HealthComponent]


class PreferenceWriteRequest(BaseModel):
    scope: MemoryScope
    key: str
    value: Any
    explicitly_confirmed: bool
    ttl_seconds: int | None = None
    expected_version: int | None = None

    def candidate(self) -> CandidateMemory:
        from financial_research_agent.memory.models import MemorySource

        return CandidateMemory(
            kind=MemoryKind.PREFERENCE,
            key=self.key,
            value=self.value,
            source=MemorySource(
                source_type="explicit_user_confirmation",
                source_id="memory_api",
            ),
            ttl_seconds=self.ttl_seconds,
            explicitly_confirmed=self.explicitly_confirmed,
        )


class MemoryListResponse(BaseModel):
    records: list[MemoryRecord]


class MemoryVersionsResponse(BaseModel):
    versions: list[MemoryVersion]


class MemoryDeleteRequest(BaseModel):
    scope: MemoryScope
    expected_version: int | None = None


class JobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=2, max_length=2000)
    session_id: str = Field(
        default="default",
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$",
    )
    queue_class: str = Field(default="interactive", pattern=r"^(interactive|batch)$")


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=2, max_length=2000)
    session_id: str = Field(
        default="default",
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$",
    )


class JobCreateResponse(BaseModel):
    job: JobSnapshot
    created: bool


class JobStatusResponse(BaseModel):
    job: JobSnapshot
    result: AnalyzeResponse | None = None


class JobEventsResponse(BaseModel):
    events: list[JobEvent]


class SessionMemoryDeleteRequest(BaseModel):
    tenant_id: str = "local"
    user_id: str = "local"
