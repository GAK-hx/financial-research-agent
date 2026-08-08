from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from financial_research_agent.domain.models import Intent, ToolName


class EvaluationCase(BaseModel):
    case_id: str = Field(
        pattern=r"^(?:eval|holdout|stability|private)-[0-9]{2,3}$"
    )
    category: str
    question: str
    expected_http_status: int = 200
    expected_success: bool = True
    expected_intent: Intent | None = None
    expected_stock_codes: list[str] = Field(default_factory=list)
    expected_start_date: date | None = None
    expected_end_date: date | None = None
    expected_tools: list[ToolName] = Field(default_factory=list)
    expected_skills: list[str] = Field(default_factory=list)
    required_evidence_types: list[str] = Field(default_factory=list)
    require_harness_controls: bool = False
    expected_error_code: str | None = None


class EvaluationDataset(BaseModel):
    dataset_version: str
    kind: Literal["regression", "holdout", "stability", "private_holdout"]
    as_of_date: date
    frozen_at: str
    cases: list[EvaluationCase]


class CaseScore(BaseModel):
    case_id: str
    category: str
    http_contract: bool
    intent_accuracy: bool | None = None
    tool_selection_accuracy: bool | None = None
    skill_selection_accuracy: bool | None = None
    argument_accuracy: bool | None = None
    semantic_alignment: bool | None = None
    evidence_coverage: bool | None = None
    citation_accuracy: bool | None = None
    numeric_consistency: bool | None = None
    evidence_support_accuracy: bool | None = None
    completion_passed: bool | None = None
    budget_closed: bool | None = None
    trajectory_redundancy: float | None = None
    task_success: bool
    planner_source: str | None = None
    api_total_ms: int | None = None
    model_calls: int = 0
    errors: list[str] = Field(default_factory=list)


class EvaluationArtifact(BaseModel):
    dataset_version: str
    dataset_sha256: str | None = None
    repetition: int = Field(default=1, ge=1)
    case: EvaluationCase
    http_status: int
    request_id: str | None = None
    response: dict[str, Any]
    score: CaseScore
