from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from financial_research_agent.governance.models import ModelUsage
from financial_research_agent.risk.agent_models import (
    AgentRequest,
    AgentRole,
    SupervisorProposal,
    TeamPlan,
)
from financial_research_agent.risk.team_harness import TeamHarness


ROLE_GUIDE = {
    AgentRole.DOCUMENT_RETRIEVAL.value: (
        "Find the relevant filing pages or passages; do not calculate the answer."
    ),
    AgentRole.TABLE_REASONING.value: (
        "Resolve headers, rows, periods, units and multi-span answers in supplied tables/text."
    ),
    AgentRole.QUANTITATIVE_ANALYSIS.value: (
        "Form and execute the arithmetic/program required by the question."
    ),
    AgentRole.RISK_INTERPRETATION.value: (
        "Interpret deterministic risk candidates and alternative business explanations."
    ),
    AgentRole.LIQUIDITY_SOLVENCY.value: (
        "Review liquidity, short-debt coverage, debt maturity and solvency candidates."
    ),
    AgentRole.EARNINGS_CASH_FLOW.value: (
        "Review earnings quality, cash conversion, accrual, receivable and inventory candidates."
    ),
    AgentRole.ASSET_QUALITY_REVIEW.value: (
        "Review impairment, goodwill, capitalization, disposal and asset-quality candidates."
    ),
    AgentRole.DISCLOSURE_AUDIT.value: (
        "Review restatement, inquiry, audit-opinion and disclosure-document evidence."
    ),
}


class TeamSelectionResult(BaseModel):
    proposal: SupervisorProposal
    plan: TeamPlan
    usage: ModelUsage


class TeamSupervisor:
    def __init__(self, provider: Any, harness: TeamHarness | None = None) -> None:
        self.provider = provider
        self.harness = harness or TeamHarness()

    async def select_team(
        self,
        *,
        benchmark: str,
        case_id: str,
        question: str,
        task_metadata: dict[str, Any] | None = None,
    ) -> TeamSelectionResult:
        response = await self.provider.create_structured_response(
            instruction=(
                "Act as a financial-analysis Supervisor. Choose the smallest useful set of "
                "registered child Agent roles for this question. A direct lookup needs only "
                "retrieval or table reasoning. Add quantitative analysis only when arithmetic "
                "or a program is required. A separate Evaluator always reviews evidence after "
                "the research Agents finish, so do not create an evidence-review child. "
                "Risk interpretation is for financial-risk tasks, not "
                "ordinary benchmark arithmetic. For risk_demo, select only the risk-domain roles "
                "that match supplied candidate categories; do not add generic risk_interpretation "
                "when a specific role exists. Do not answer the question. Do not propose "
                "tools, budgets, or nested Agents; the Harness owns those controls. For FinQA "
                "and TAT-QA, the relevant table and text are already supplied in the case, so "
                "do not add document retrieval merely because the question mentions a filing. "
                "Choose quantitative analysis only for explicit arithmetic, comparison, rate, "
                "change, or amount questions. A question asking what someone is paid 'on' or "
                "'under' a contract may ask for the payment basis; use the context preview to "
                "distinguish a definition from an amount."
            ),
            input_payload={
                "benchmark": benchmark,
                "case_id": case_id,
                "question": question,
                "task_metadata": task_metadata or {},
                "registered_roles": ROLE_GUIDE,
            },
            schema=SupervisorProposal,
            max_tokens=700,
            operation="risk_team_selection",
        )
        proposal = SupervisorProposal.model_validate(response.content)
        plan = self.harness.build_plan(
            benchmark=benchmark,
            case_id=case_id,
            proposal=proposal,
        )
        return TeamSelectionResult(
            proposal=proposal,
            plan=plan,
            usage=response.usage,
        )


FIXED_TEAM_ROLES: dict[str, tuple[AgentRole, ...]] = {
    "financebench": (
        AgentRole.DOCUMENT_RETRIEVAL,
        AgentRole.TABLE_REASONING,
        AgentRole.QUANTITATIVE_ANALYSIS,
    ),
    "finqa": (
        AgentRole.TABLE_REASONING,
        AgentRole.QUANTITATIVE_ANALYSIS,
    ),
    "tatqa": (
        AgentRole.TABLE_REASONING,
        AgentRole.QUANTITATIVE_ANALYSIS,
    ),
    "risk_demo": (
        AgentRole.LIQUIDITY_SOLVENCY,
        AgentRole.EARNINGS_CASH_FLOW,
        AgentRole.ASSET_QUALITY_REVIEW,
        AgentRole.DISCLOSURE_AUDIT,
    ),
}


class FixedTeamSupervisor:
    """Deterministic fixed-team selector used only as ablation configuration C."""

    def __init__(self, harness: TeamHarness | None = None) -> None:
        self.harness = harness or TeamHarness()

    async def select_team(
        self,
        *,
        benchmark: str,
        case_id: str,
        question: str,
        task_metadata: dict[str, Any] | None = None,
    ) -> TeamSelectionResult:
        del question, task_metadata
        roles = FIXED_TEAM_ROLES.get(benchmark)
        if roles is None:
            raise ValueError(f"BENCHMARK_UNSUPPORTED:{benchmark}")
        proposal = SupervisorProposal(
            task_summary=(
                "Fixed-team ablation: run every benchmark-registered research role regardless "
                "of per-question complexity."
            ),
            requests=[
                AgentRequest(
                    role=role,
                    objective=(
                        f"Apply the fixed-team {role.value} method to the supplied controlled "
                        "context and produce an independently reviewable hypothesis."
                    ),
                    rationale="Fixed ablation configuration C.",
                )
                for role in roles
            ],
        )
        return TeamSelectionResult(
            proposal=proposal,
            plan=self.harness.build_plan(
                benchmark=benchmark,
                case_id=case_id,
                proposal=proposal,
            ),
            usage=ModelUsage(),
        )
