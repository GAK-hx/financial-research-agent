from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from financial_research_agent.governance.models import ModelUsage
from financial_research_agent.risk.domain.models import RiskCategory, RiskStatus


class AgentRole(StrEnum):
    DOCUMENT_RETRIEVAL = "document_retrieval"
    TABLE_REASONING = "table_reasoning"
    QUANTITATIVE_ANALYSIS = "quantitative_analysis"
    RISK_INTERPRETATION = "risk_interpretation"
    EVIDENCE_REVIEW = "evidence_review"
    LIQUIDITY_SOLVENCY = "liquidity_solvency"
    EARNINGS_CASH_FLOW = "earnings_cash_flow"
    ASSET_QUALITY_REVIEW = "asset_quality_review"
    DISCLOSURE_AUDIT = "disclosure_audit"


class EvaluationDecision(StrEnum):
    ACCEPT = "ACCEPT"
    ACCEPT_WITH_LIMITATIONS = "ACCEPT_WITH_LIMITATIONS"
    TARGETED_REPAIR = "TARGETED_REPAIR"
    REJECT = "REJECT"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class RiskCandidate(BaseModel):
    candidate_id: str
    subject_id: str
    category: RiskCategory
    status: RiskStatus
    signal: str
    current_value: float | None = None
    historical_baseline: float | None = None
    formula: str | None = None
    threshold: str | None = None
    unit: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    data_version: str = ""


class AgentRequest(BaseModel):
    role: AgentRole
    objective: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(default="", max_length=1000)


class SupervisorProposal(BaseModel):
    task_summary: str = Field(min_length=1, max_length=1000)
    requests: list[AgentRequest] = Field(min_length=1, max_length=8)


class SubAgentSpec(BaseModel):
    agent_id: str
    role: AgentRole
    objective: str
    allowed_tools: list[str]
    max_tool_calls: int = Field(ge=0)
    max_tokens: int = Field(gt=0)
    timeout_seconds: int = Field(gt=0)
    may_spawn_children: Literal[False] = False


class TeamPlan(BaseModel):
    benchmark: Literal["financebench", "finqa", "tatqa", "risk_demo"]
    case_id: str
    task_summary: str
    agents: list[SubAgentSpec] = Field(min_length=1, max_length=4)
    evaluator_enabled: bool = True
    max_repairs: Literal[0, 1] = 1
    total_tool_call_budget: int = Field(ge=0)
    total_token_budget: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_team(self) -> TeamPlan:
        identifiers = [agent.agent_id for agent in self.agents]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("agent_id values must be unique")
        if sum(agent.max_tool_calls for agent in self.agents) > self.total_tool_call_budget:
            raise ValueError("agent tool budgets exceed the team budget")
        if sum(agent.max_tokens for agent in self.agents) > self.total_token_budget:
            raise ValueError("agent token budgets exceed the team budget")
        return self


class EvidenceReference(BaseModel):
    evidence_id: str
    source: str
    locator: str
    excerpt: str = Field(default="", max_length=4000)


class RiskHypothesis(BaseModel):
    agent_id: str
    role: AgentRole
    conclusion: str
    answer_candidate: str | list[str] | None = None
    scale: str = ""
    program: str | None = None
    supporting_evidence: list[EvidenceReference] = Field(default_factory=list)
    counterevidence: list[EvidenceReference] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    severity: Literal["low", "medium", "high", "unknown"] = "unknown"
    confidence: float = Field(default=0.5, ge=0, le=1)


class SubAgentRun(BaseModel):
    hypothesis: RiskHypothesis
    usage: ModelUsage
    tool_calls: int = Field(ge=0)
    latency_seconds: float = Field(ge=0)
    revision: bool = False


class SubAgentEvaluation(BaseModel):
    decision: EvaluationDecision
    accepted_agent_ids: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    repair_agent_id: str | None = None
    repair_instruction: str | None = None

    @model_validator(mode="after")
    def validate_repair(self) -> SubAgentEvaluation:
        if self.decision == EvaluationDecision.TARGETED_REPAIR:
            if not self.repair_agent_id or not self.repair_instruction:
                raise ValueError("targeted repair requires an agent and instruction")
        return self


class AgentContribution(BaseModel):
    agent_id: str
    role: AgentRole
    accepted: bool
    tool_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_seconds: float = Field(ge=0)
    contribution: str = ""


class AgentScorecard(BaseModel):
    benchmark: str
    case_id: str
    decision: EvaluationDecision
    repair_count: int = Field(ge=0, le=1)
    contributions: list[AgentContribution]
    total_tool_calls: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    total_latency_seconds: float = Field(ge=0)


class RiskFinding(BaseModel):
    agent_id: str
    role: AgentRole
    category: str
    candidate_status: str = ""
    conclusion: str
    severity: Literal["low", "medium", "high", "unknown"] = "unknown"
    confidence: float = Field(default=0.5, ge=0, le=1)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    counterevidence_ids: list[str] = Field(default_factory=list)
    accepted: bool


class RiskAssessmentArtifact(BaseModel):
    benchmark: str
    case_id: str
    subject_id: str = ""
    report_period: str = ""
    as_of_date: str = ""
    data_snapshot_id: str = ""
    answer: str | list[str]
    scale: str = ""
    program: str | None = None
    evidence: list[EvidenceReference] = Field(default_factory=list)
    risks: list[RiskFinding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    evaluation: SubAgentEvaluation
    scorecard: AgentScorecard
