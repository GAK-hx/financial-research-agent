from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from financial_research_agent.domain.models import Intent, QuerySpec, ToolName


class SkillStatus(StrEnum):
    DRAFT = "DRAFT"
    REVIEWED = "REVIEWED"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class SkillType(StrEnum):
    RESEARCH = "research"
    RETRIEVAL = "retrieval"
    REPORT = "report"
    REVIEW = "review"


class TriggerRule(BaseModel):
    intents: list[Intent] = Field(min_length=1)
    any_dimensions: list[str] = Field(default_factory=list)

    def matches(self, query: QuerySpec) -> bool:
        return query.intent in self.intents and (
            not self.any_dimensions
            or bool(set(self.any_dimensions).intersection(query.dimensions))
        )


class EvidenceRequirement(BaseModel):
    evidence_type: Literal[
        "market", "financial", "indicator", "research_report", "technical",
        "fundamental", "factor", "event", "comparison"
    ]
    minimum_count: int = Field(default=1, ge=1, le=20)


class WorkflowConstraints(BaseModel):
    max_tool_calls: int = Field(default=8, ge=0, le=20)
    max_model_calls: int = Field(default=3, ge=0, le=10)
    max_parallel_tools: int = Field(default=4, ge=1, le=8)
    max_report_revisions: int = Field(default=1, ge=0, le=1)
    replan_limit: int = Field(default=0, ge=0, le=1)


class SkillDefinition(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    status: SkillStatus
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(min_length=5, max_length=500)
    skill_type: SkillType
    triggers: list[TriggerRule] = Field(min_length=1)
    allowed_tools: list[ToolName] = Field(min_length=1)
    required_evidence: list[EvidenceRequirement] = Field(default_factory=list)
    workflow_constraints: WorkflowConstraints = Field(
        default_factory=WorkflowConstraints
    )
    context_policy: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    report_sections: list[str] = Field(default_factory=list)
    validator_profile: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    budget_profile: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    prompt_refs: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    owner: str = Field(min_length=2, max_length=100)
    supersedes: str | None = None
    checksum: str = ""

    @model_validator(mode="after")
    def validate_and_checksum(self) -> SkillDefinition:
        if len(self.allowed_tools) != len(set(self.allowed_tools)):
            raise ValueError("allowed_tools must be unique")
        if self.id in self.conflicts_with:
            raise ValueError("skill cannot conflict with itself")
        # Lifecycle state is deliberately excluded: reviewing/activating an
        # unchanged definition must not change its content identity.
        payload = self.model_dump(mode="json", exclude={"checksum", "status"})
        expected = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if self.checksum and self.checksum != expected:
            raise ValueError("skill checksum does not match definition")
        self.checksum = expected
        return self

    @property
    def version_id(self) -> str:
        return f"{self.id}@{self.version}"

    def matches(self, query: QuerySpec) -> bool:
        return any(trigger.matches(query) for trigger in self.triggers)


class SkillSnapshot(BaseModel):
    skill_id: str
    version: str
    version_id: str
    checksum: str
    skill_type: SkillType
    allowed_tools: list[ToolName]
    required_evidence: list[EvidenceRequirement]
    workflow_constraints: WorkflowConstraints
    context_policy: str
    validator_profile: str
    budget_profile: str
    report_sections: list[str]

    @classmethod
    def from_definition(cls, value: SkillDefinition) -> SkillSnapshot:
        return cls(
            skill_id=value.id,
            version=value.version,
            version_id=value.version_id,
            checksum=value.checksum,
            skill_type=value.skill_type,
            allowed_tools=value.allowed_tools,
            required_evidence=value.required_evidence,
            workflow_constraints=value.workflow_constraints,
            context_policy=value.context_policy,
            validator_profile=value.validator_profile,
            budget_profile=value.budget_profile,
            report_sections=value.report_sections,
        )


class ReportProfile(BaseModel):
    id: Literal["standard", "concise", "risk"]
    max_claims: int = Field(ge=1, le=30)
    section_order: list[str] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)


class SkillSelection(BaseModel):
    snapshots: list[SkillSnapshot] = Field(default_factory=list)
    reason: str
    effective_allowed_tools: list[ToolName] = Field(default_factory=list)
    required_evidence: list[EvidenceRequirement] = Field(default_factory=list)
    workflow_constraints: WorkflowConstraints = Field(
        default_factory=WorkflowConstraints
    )
    report_profiles: list[ReportProfile] = Field(default_factory=list)

    @property
    def selected_ids(self) -> list[str]:
        return [item.version_id for item in self.snapshots]
