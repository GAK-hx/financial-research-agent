from __future__ import annotations

from dataclasses import dataclass

from financial_research_agent.risk.agents.agent_models import (
    AgentRequest,
    AgentRole,
    SubAgentSpec,
    SupervisorProposal,
    TeamPlan,
)


@dataclass(frozen=True)
class AgentTemplate:
    allowed_tools: tuple[str, ...]
    max_tool_calls: int
    max_tokens: int
    timeout_seconds: int


DEFAULT_AGENT_TEMPLATES: dict[AgentRole, AgentTemplate] = {
    AgentRole.DOCUMENT_RETRIEVAL: AgentTemplate(
        allowed_tools=("financebench_page_search", "context_reader"),
        max_tool_calls=4,
        max_tokens=1800,
        timeout_seconds=45,
    ),
    AgentRole.TABLE_REASONING: AgentTemplate(
        allowed_tools=("context_reader", "table_reader"),
        max_tool_calls=2,
        max_tokens=1800,
        timeout_seconds=45,
    ),
    AgentRole.QUANTITATIVE_ANALYSIS: AgentTemplate(
        allowed_tools=("calculator", "finqa_program_executor", "context_reader"),
        max_tool_calls=3,
        max_tokens=1800,
        timeout_seconds=45,
    ),
    AgentRole.RISK_INTERPRETATION: AgentTemplate(
        allowed_tools=("risk_candidate_reader", "context_reader"),
        max_tool_calls=2,
        max_tokens=1800,
        timeout_seconds=45,
    ),
    AgentRole.EVIDENCE_REVIEW: AgentTemplate(
        allowed_tools=("evidence_checker", "calculator"),
        max_tool_calls=2,
        max_tokens=1400,
        timeout_seconds=45,
    ),
    AgentRole.LIQUIDITY_SOLVENCY: AgentTemplate(
        allowed_tools=("risk_candidate_reader", "context_reader", "calculator"),
        max_tool_calls=3,
        max_tokens=1800,
        timeout_seconds=45,
    ),
    AgentRole.EARNINGS_CASH_FLOW: AgentTemplate(
        allowed_tools=("risk_candidate_reader", "context_reader", "calculator"),
        max_tool_calls=3,
        max_tokens=1800,
        timeout_seconds=45,
    ),
    AgentRole.ASSET_QUALITY_REVIEW: AgentTemplate(
        allowed_tools=("risk_candidate_reader", "context_reader", "calculator"),
        max_tool_calls=3,
        max_tokens=1800,
        timeout_seconds=45,
    ),
    AgentRole.DISCLOSURE_AUDIT: AgentTemplate(
        allowed_tools=("risk_candidate_reader", "context_reader", "evidence_checker"),
        max_tool_calls=3,
        max_tokens=1800,
        timeout_seconds=45,
    ),
}

BENCHMARK_TOOL_ALLOWLISTS: dict[str, frozenset[str]] = {
    "financebench": frozenset(
        {"financebench_page_search", "context_reader", "calculator", "evidence_checker"}
    ),
    "finqa": frozenset(
        {"context_reader", "table_reader", "calculator", "finqa_program_executor", "evidence_checker"}
    ),
    "tatqa": frozenset(
        {"context_reader", "table_reader", "calculator", "evidence_checker"}
    ),
    "risk_demo": frozenset(
        {"risk_candidate_reader", "context_reader", "calculator", "evidence_checker"}
    ),
}


class TeamHarness:
    """Turn an LLM team proposal into an executable, budgeted plan.

    The model chooses roles and objectives. Tool access and execution budgets come only
    from code-owned templates, so the model cannot grant itself new capabilities.
    """

    def __init__(
        self,
        templates: dict[AgentRole, AgentTemplate] | None = None,
        *,
        max_research_agents: int = 4,
        max_total_tool_calls: int = 10,
        max_total_tokens: int = 7200,
    ) -> None:
        self.templates = templates or DEFAULT_AGENT_TEMPLATES
        self.max_research_agents = max_research_agents
        self.max_total_tool_calls = max_total_tool_calls
        self.max_total_tokens = max_total_tokens

    def build_plan(
        self,
        *,
        benchmark: str,
        case_id: str,
        proposal: SupervisorProposal,
    ) -> TeamPlan:
        # Preserve Supervisor priority while removing duplicate roles. Extra proposals
        # are clipped at the controlled execution boundary instead of rejecting the case.
        unique_requests = []
        seen_roles: set[AgentRole] = set()
        for request in proposal.requests:
            if request.role in seen_roles or request.role not in self.templates:
                continue
            seen_roles.add(request.role)
            unique_requests.append(request)
            if len(unique_requests) >= self.max_research_agents:
                break
        if (
            benchmark == "finqa"
            and AgentRole.QUANTITATIVE_ANALYSIS not in seen_roles
        ):
            required = AgentRequest(
                role=AgentRole.QUANTITATIVE_ANALYSIS,
                objective=(
                    "Produce and execute the FinQA functional program required by the "
                    "public benchmark task."
                ),
                rationale="Every FinQA case is scored on an executable program.",
            )
            if len(unique_requests) >= self.max_research_agents:
                unique_requests[-1] = required
            else:
                unique_requests.append(required)
            seen_roles.add(AgentRole.QUANTITATIVE_ANALYSIS)
        if not unique_requests:
            raise ValueError("TEAM_EMPTY:no registered Agent role was selected")

        agents: list[SubAgentSpec] = []
        benchmark_tools = BENCHMARK_TOOL_ALLOWLISTS.get(benchmark)
        if benchmark_tools is None:
            raise ValueError(f"BENCHMARK_UNSUPPORTED:{benchmark}")
        remaining_tools = self.max_total_tool_calls
        remaining_tokens = self.max_total_tokens
        for index, request in enumerate(unique_requests, start=1):
            template = self.templates[request.role]
            allowed_tools = [
                tool for tool in template.allowed_tools if tool in benchmark_tools
            ]
            tool_budget = min(
                template.max_tool_calls if allowed_tools else 0,
                remaining_tools,
            )
            token_budget = min(template.max_tokens, remaining_tokens)
            if token_budget <= 0:
                break
            agents.append(
                SubAgentSpec(
                    agent_id=f"agent-{index}-{request.role.value}",
                    role=request.role,
                    objective=request.objective,
                    allowed_tools=allowed_tools,
                    max_tool_calls=tool_budget,
                    max_tokens=token_budget,
                    timeout_seconds=template.timeout_seconds,
                )
            )
            remaining_tools -= tool_budget
            remaining_tokens -= token_budget
        if not agents:
            raise ValueError("TEAM_BUDGET_EXHAUSTED:no Agent fits the configured budget")

        return TeamPlan(
            benchmark=benchmark,
            case_id=case_id,
            task_summary=proposal.task_summary,
            agents=agents,
            evaluator_enabled=True,
            max_repairs=1,
            total_tool_call_budget=self.max_total_tool_calls,
            total_token_budget=self.max_total_tokens,
        )
