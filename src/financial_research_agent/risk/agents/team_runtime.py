from __future__ import annotations

import operator
import time
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from financial_research_agent.risk.agents.agent_models import (
    AgentContribution,
    AgentRole,
    AgentScorecard,
    EvaluationDecision,
    EvidenceReference,
    RiskAssessmentArtifact,
    RiskFinding,
    RiskHypothesis,
    SubAgentEvaluation,
    SubAgentRun,
    SubAgentSpec,
    TeamPlan,
)
from financial_research_agent.risk.benchmarks.finqa_tools import (
    canonicalize_finqa_program,
    execute_finqa_program,
)
from financial_research_agent.risk.benchmarks.public_benchmark_runner import _answer_schema
from financial_research_agent.risk.agents.team_supervisor import TeamSupervisor


ROLE_INSTRUCTIONS = {
    AgentRole.DOCUMENT_RETRIEVAL: (
        "Locate the smallest set of passages that answers the question. Preserve page locators, "
        "periods and units. Do not perform unsupported arithmetic."
    ),
    AgentRole.TABLE_REASONING: (
        "Resolve table headers, rows, periods, units and exact spans. Distinguish text from table "
        "claims and do not infer a missing value."
    ),
    AgentRole.QUANTITATIVE_ANALYSIS: (
        "Form the required arithmetic from supplied values. For FinQA, return one official-style "
        "program. State assumptions and do not silently change scale."
    ),
    AgentRole.RISK_INTERPRETATION: (
        "Interpret only supplied deterministic signals and evidence. Consider alternative "
        "explanations and distinguish facts from risk interpretation."
    ),
    AgentRole.EVIDENCE_REVIEW: (
        "Check answer candidates against supplied evidence, including sign, period, unit, scale "
        "and locator. Explicitly record counterevidence or missing information."
    ),
    AgentRole.LIQUIDITY_SOLVENCY: (
        "Assess only liquidity and solvency candidates: cash versus short debt, current coverage, "
        "operating cash coverage, debt maturity and financing pressure. Test benign explanations "
        "and keep point-in-time boundaries explicit."
    ),
    AgentRole.EARNINGS_CASH_FLOW: (
        "Assess only earnings quality and cash conversion: profit versus operating cash flow, "
        "accruals, receivables, inventory, non-recurring gains and persistence. Separate weak "
        "cash conversion from ordinary growth investment."
    ),
    AgentRole.ASSET_QUALITY_REVIEW: (
        "Assess only asset quality: impairment, goodwill, capitalization, disposal, capex and "
        "asset-utilization signals. Distinguish accounting remeasurement from operating distress."
    ),
    AgentRole.DISCLOSURE_AUDIT: (
        "Assess only disclosure and audit evidence: restatements, inquiry letters, qualified "
        "opinions, revisions and document inconsistencies. A title match is a candidate, not "
        "proof; require the supplied document evidence."
    ),
}

ROLE_RISK_CATEGORIES = {
    AgentRole.LIQUIDITY_SOLVENCY: "liquidity",
    AgentRole.EARNINGS_CASH_FLOW: "earnings_quality",
    AgentRole.ASSET_QUALITY_REVIEW: "asset_quality",
    AgentRole.DISCLOSURE_AUDIT: "disclosure_audit",
}


def build_risk_findings(
    runs: list[SubAgentRun],
    evaluation: SubAgentEvaluation,
    controlled_context: dict[str, Any],
) -> list[RiskFinding]:
    candidate_by_category = {
        str(item.get("category", "")): item
        for item in controlled_context.get("risk_candidates", [])
    }
    findings: list[RiskFinding] = []
    for run in runs:
        category = ROLE_RISK_CATEGORIES.get(run.hypothesis.role)
        if category is None:
            continue
        candidate = candidate_by_category.get(category, {})
        findings.append(
            RiskFinding(
                agent_id=run.hypothesis.agent_id,
                role=run.hypothesis.role,
                category=category,
                candidate_status=str(candidate.get("status", "")),
                conclusion=run.hypothesis.conclusion,
                severity=run.hypothesis.severity,
                confidence=run.hypothesis.confidence,
                supporting_evidence_ids=[
                    item.evidence_id for item in run.hypothesis.supporting_evidence
                ],
                counterevidence_ids=[
                    item.evidence_id for item in run.hypothesis.counterevidence
                ],
                accepted=run.hypothesis.agent_id in evaluation.accepted_agent_ids,
            )
        )
    return findings


class TeamGraphState(TypedDict, total=False):
    benchmark: str
    case_id: str
    question: str
    task_metadata: dict[str, Any]
    controlled_context: dict[str, Any]
    preparation_tool_calls: int
    preparation_usage: list[dict[str, Any]]
    team_plan: dict[str, Any]
    supervisor_usage: dict[str, Any]
    agent_spec: dict[str, Any]
    repair_instruction: str
    agent_runs: Annotated[list[dict[str, Any]], operator.add]
    evaluations: Annotated[list[dict[str, Any]], operator.add]
    repair_count: int
    final_answer: dict[str, Any]
    artifact: dict[str, Any]
    node_trace: Annotated[list[str], operator.add]


class BenchmarkTeamRuntime:
    """LangGraph runtime for dynamic, budgeted public-benchmark teams."""

    def __init__(self, provider: Any, supervisor: TeamSupervisor | None = None) -> None:
        self.provider = provider
        self.supervisor = supervisor or TeamSupervisor(provider)
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(TeamGraphState)
        builder.add_node("select_team", self._select_team)
        builder.add_node("run_agent", self._run_agent)
        builder.add_node("evaluate", self._evaluate)
        builder.add_node("repair", self._repair)
        builder.add_node("synthesize", self._synthesize)
        builder.add_edge(START, "select_team")
        builder.add_conditional_edges("select_team", self._dispatch_agents)
        builder.add_edge("run_agent", "evaluate")
        builder.add_conditional_edges(
            "evaluate",
            self._route_evaluation,
            {"repair": "repair", "synthesize": "synthesize"},
        )
        builder.add_edge("repair", "evaluate")
        builder.add_edge("synthesize", END)
        return builder.compile()

    async def _select_team(self, state: TeamGraphState) -> dict[str, Any]:
        selected = await self.supervisor.select_team(
            benchmark=state["benchmark"],
            case_id=state["case_id"],
            question=state["question"],
            task_metadata=state.get("task_metadata"),
        )
        return {
            "team_plan": selected.plan.model_dump(mode="json"),
            "supervisor_usage": selected.usage.model_dump(mode="json"),
            "repair_count": 0,
            "agent_runs": [],
            "evaluations": [],
            "node_trace": ["select_team"],
        }

    def _dispatch_agents(self, state: TeamGraphState) -> list[Send]:
        plan = TeamPlan.model_validate(state["team_plan"])
        return [
            Send(
                "run_agent",
                {
                    "benchmark": state["benchmark"],
                    "case_id": state["case_id"],
                    "question": state["question"],
                    "controlled_context": state["controlled_context"],
                    "preparation_tool_calls": state.get("preparation_tool_calls", 0),
                    "agent_spec": spec.model_dump(mode="json"),
                    "repair_count": 0,
                },
            )
            for spec in plan.agents
        ]

    async def _invoke_agent(
        self,
        *,
        benchmark: str,
        case_id: str,
        question: str,
        controlled_context: dict[str, Any],
        spec: SubAgentSpec,
        tool_calls: int,
        repair_instruction: str = "",
    ) -> SubAgentRun:
        started = time.perf_counter()
        benchmark_instruction = ""
        if benchmark == "finqa" and spec.role == AgentRole.QUANTITATIVE_ANALYSIS:
            benchmark_instruction = (
                " Return program in official functional syntax such as "
                "divide(637, 5.0), never infix syntax such as 637 / 5.0. When public train-split "
                "program examples are present, use them only to learn operator and constant "
                "conventions; never copy their answer as evidence for the current case."
            )
        elif benchmark == "tatqa":
            benchmark_instruction = (
                " For descriptive span questions, preserve the complete directly responsive "
                "source clause, including qualifications; do not shorten it to a paraphrase."
            )
        response = await self.provider.create_structured_response(
            instruction=(
                f"You are the {spec.role.value} child Agent. {ROLE_INSTRUCTIONS[spec.role]} "
                "Work only from controlled_context, which is the output of Harness-approved "
                "read-only tools. Do not request or assume other data. Return a RiskHypothesis. "
                "The answer_candidate should be the shortest usable candidate, not a report."
                f"{benchmark_instruction}"
            ),
            input_payload={
                "benchmark": benchmark,
                "case_id": case_id,
                "question": question,
                "agent_id": spec.agent_id,
                "role": spec.role.value,
                "objective": spec.objective,
                "allowed_tools": spec.allowed_tools,
                "controlled_context": controlled_context,
                "repair_instruction": repair_instruction,
            },
            schema=RiskHypothesis,
            max_tokens=spec.max_tokens,
            operation=f"risk_subagent_{spec.role.value}",
        )
        hypothesis = RiskHypothesis.model_validate(response.content).model_copy(
            update={"agent_id": spec.agent_id, "role": spec.role}
        )
        if (
            benchmark == "finqa"
            and spec.role == AgentRole.QUANTITATIVE_ANALYSIS
            and hypothesis.program
        ):
            canonical_program = canonicalize_finqa_program(hypothesis.program)
            hypothesis = hypothesis.model_copy(update={"program": canonical_program})
            table = controlled_context.get("context", {}).get("table") or []
            execution = execute_finqa_program(hypothesis.program, table)
            tool_calls += 1
            if execution.valid:
                hypothesis = hypothesis.model_copy(
                    update={
                        "supporting_evidence": [
                            *hypothesis.supporting_evidence,
                            EvidenceReference(
                                evidence_id=f"{spec.agent_id}:program-execution",
                                source="finqa_program_executor",
                                locator="controlled local execution",
                                excerpt=(
                                    f"program={hypothesis.program}; "
                                    f"result={execution.value}; "
                                    f"steps={execution.steps_executed}"
                                ),
                            ),
                        ]
                    }
                )
            else:
                hypothesis = hypothesis.model_copy(
                    update={
                        "missing_information": [
                            *hypothesis.missing_information,
                            f"PROGRAM_EXECUTION_FAILED:{execution.error}",
                        ],
                        "confidence": min(hypothesis.confidence, 0.4),
                    }
                )
        return SubAgentRun(
            hypothesis=hypothesis,
            usage=response.usage,
            tool_calls=min(tool_calls, spec.max_tool_calls),
            latency_seconds=round(time.perf_counter() - started, 3),
            revision=bool(repair_instruction),
        )

    async def _run_agent(self, state: TeamGraphState) -> dict[str, Any]:
        spec = SubAgentSpec.model_validate(state["agent_spec"])
        tool_calls = (
            state.get("preparation_tool_calls", 0)
            if spec.role == AgentRole.DOCUMENT_RETRIEVAL
            else int(bool(state.get("controlled_context")))
        )
        if (
            state["benchmark"] == "finqa"
            and spec.role == AgentRole.QUANTITATIVE_ANALYSIS
            and state.get("controlled_context", {}).get("finqa_program_skill")
        ):
            tool_calls += 1
        run = await self._invoke_agent(
            benchmark=state["benchmark"],
            case_id=state["case_id"],
            question=state["question"],
            controlled_context=state["controlled_context"],
            spec=spec,
            tool_calls=tool_calls,
        )
        return {
            "agent_runs": [run.model_dump(mode="json")],
            "node_trace": [f"run_agent:{spec.role.value}"],
        }

    async def _evaluate(self, state: TeamGraphState) -> dict[str, Any]:
        plan = TeamPlan.model_validate(state["team_plan"])
        all_runs = [SubAgentRun.model_validate(item) for item in state["agent_runs"]]
        latest_by_agent = {run.hypothesis.agent_id: run for run in all_runs}
        runs = list(latest_by_agent.values())
        evaluation_context: dict[str, Any]
        if state["benchmark"] == "financebench":
            evaluation_context = {
                "extracted_evidence": [
                    item.model_dump(mode="json")
                    for run in runs
                    for item in [
                        *run.hypothesis.supporting_evidence,
                        *run.hypothesis.counterevidence,
                    ]
                ]
            }
        else:
            evaluation_context = state["controlled_context"]
        response = await self.provider.create_structured_response(
            instruction=(
                "Act as the independent Evaluator. Compare child hypotheses with the supplied "
                "controlled evidence. Check period, units, scale, arithmetic, citations, conflicts "
                "and missing evidence. Do not use outside facts or benchmark Gold. Prefer ACCEPT "
                "or ACCEPT_WITH_LIMITATIONS when the answer is supported. Use TARGETED_REPAIR only "
                "for one specific correctable gap and name exactly one existing agent_id. Do not "
                "invent a most-recent period when the question asks for a definition or process; "
                "prefer the directly responsive text span over a nearby numeric table."
            ),
            input_payload={
                "benchmark": state["benchmark"],
                "case_id": state["case_id"],
                "question": state["question"],
                "controlled_context": evaluation_context,
                "hypotheses": [run.hypothesis.model_dump(mode="json") for run in runs],
                "repair_count": state.get("repair_count", 0),
                "maximum_repairs": plan.max_repairs,
            },
            schema=SubAgentEvaluation,
            max_tokens=1200,
            operation="risk_team_evaluation",
        )
        evaluation = SubAgentEvaluation.model_validate(response.content)
        if state["benchmark"] == "finqa":
            failed_program_runs = [
                run
                for run in runs
                if run.hypothesis.role == AgentRole.QUANTITATIVE_ANALYSIS
                and any(
                    item.startswith("PROGRAM_EXECUTION_FAILED:")
                    for item in run.hypothesis.missing_information
                )
            ]
            if failed_program_runs and state.get("repair_count", 0) < plan.max_repairs:
                failed = failed_program_runs[0]
                evaluation = SubAgentEvaluation(
                    decision=EvaluationDecision.TARGETED_REPAIR,
                    accepted_agent_ids=[
                        run.hypothesis.agent_id
                        for run in runs
                        if run.hypothesis.agent_id != failed.hypothesis.agent_id
                    ],
                    unsupported_claims=["FinQA program failed controlled execution."],
                    repair_agent_id=failed.hypothesis.agent_id,
                    repair_instruction=(
                        "Rewrite only the program in official sequential functional syntax. "
                        "Do not nest operations: use #0, #1 references, for example "
                        "subtract(10, 4), divide(#0, const_2). Preserve the evidence-backed answer."
                    ),
                )
            elif failed_program_runs:
                evaluation = evaluation.model_copy(
                    update={
                        "decision": EvaluationDecision.REJECT,
                        "unsupported_claims": [
                            *evaluation.unsupported_claims,
                            "FinQA program still fails controlled execution after repair.",
                        ],
                        "repair_agent_id": None,
                        "repair_instruction": None,
                    }
                )
        valid_agent_ids = {agent.agent_id for agent in plan.agents}
        accepted = [
            agent_id
            for agent_id in evaluation.accepted_agent_ids
            if agent_id in valid_agent_ids
        ]
        repair_agent_id = (
            evaluation.repair_agent_id
            if evaluation.repair_agent_id in valid_agent_ids
            else None
        )
        if (
            evaluation.decision == EvaluationDecision.TARGETED_REPAIR
            and not repair_agent_id
        ):
            evaluation = evaluation.model_copy(
                update={
                    "decision": EvaluationDecision.ACCEPT_WITH_LIMITATIONS,
                    "repair_agent_id": None,
                    "repair_instruction": None,
                    "missing_evidence": [
                        *evaluation.missing_evidence,
                        "Evaluator requested an unknown repair Agent.",
                    ],
                }
            )
        else:
            evaluation = evaluation.model_copy(
                update={
                    "accepted_agent_ids": accepted,
                    "repair_agent_id": repair_agent_id,
                }
            )
        evaluation_row = evaluation.model_dump(mode="json")
        evaluation_row["usage"] = response.usage.model_dump(mode="json")
        return {
            "evaluations": [evaluation_row],
            "node_trace": ["evaluate"],
        }

    def _route_evaluation(self, state: TeamGraphState) -> str:
        latest = SubAgentEvaluation.model_validate(state["evaluations"][-1])
        if (
            latest.decision == EvaluationDecision.TARGETED_REPAIR
            and state.get("repair_count", 0) < 1
        ):
            return "repair"
        return "synthesize"

    async def _repair(self, state: TeamGraphState) -> dict[str, Any]:
        plan = TeamPlan.model_validate(state["team_plan"])
        evaluation = SubAgentEvaluation.model_validate(state["evaluations"][-1])
        spec = next(
            agent for agent in plan.agents if agent.agent_id == evaluation.repair_agent_id
        )
        run = await self._invoke_agent(
            benchmark=state["benchmark"],
            case_id=state["case_id"],
            question=state["question"],
            controlled_context=state["controlled_context"],
            spec=spec,
            tool_calls=min(1, spec.max_tool_calls),
            repair_instruction=evaluation.repair_instruction or "",
        )
        return {
            "agent_runs": [run.model_dump(mode="json")],
            "repair_count": state.get("repair_count", 0) + 1,
            "node_trace": [f"repair:{spec.role.value}"],
        }

    async def _synthesize(self, state: TeamGraphState) -> dict[str, Any]:
        all_runs = [SubAgentRun.model_validate(item) for item in state["agent_runs"]]
        latest_by_agent = {run.hypothesis.agent_id: run for run in all_runs}
        latest_runs = list(latest_by_agent.values())
        evaluation = SubAgentEvaluation.model_validate(state["evaluations"][-1])
        answer_schema = _answer_schema(state["benchmark"])
        span_instruction = (
            " For TAT-QA descriptive span answers, preserve the complete directly responsive "
            "source span and its qualifications instead of shortening or paraphrasing it."
            if state["benchmark"] == "tatqa"
            else ""
        )
        response = await self.provider.create_structured_response(
            instruction=(
                "Synthesize the shortest final benchmark answer from the child hypotheses and "
                "Evaluator decision. Use only controlled evidence. Preserve answer units and "
                "scale. For FinanceBench include the minimum sufficient one-based evidence_pages; "
                "do not add corroborating pages when one page fully supports the answer. For FinQA include an "
                "official-style program; for TAT-QA use the dataset scale and list for multi-span."
                " Preserve every quantity needed to answer or qualify the question; do not reduce "
                "an identification-plus-magnitude answer to only the entity name."
                " When the question asks an explicit yes/no question, begin with Yes or No and "
                "ensure the following qualitative wording does not contradict that decision."
                f"{span_instruction}"
            ),
            input_payload={
                "benchmark": state["benchmark"],
                "question": state["question"],
                "hypotheses": [
                    run.hypothesis.model_dump(mode="json") for run in latest_runs
                ],
                "evaluation": evaluation.model_dump(mode="json"),
            },
            schema=answer_schema,
            max_tokens=1600,
            operation="risk_team_synthesis",
        )
        answer = answer_schema.model_validate(response.content)
        if state["benchmark"] == "finqa":
            for run in reversed(latest_runs):
                if (
                    run.hypothesis.role == AgentRole.QUANTITATIVE_ANALYSIS
                    and run.hypothesis.program
                ):
                    table = (
                        state["controlled_context"].get("context", {}).get("table")
                        or []
                    )
                    execution = execute_finqa_program(run.hypothesis.program, table)
                    if execution.valid:
                        answer = answer.model_copy(
                            update={"program": run.hypothesis.program}
                        )
                        break
        contributions = [
            AgentContribution(
                agent_id=run.hypothesis.agent_id,
                role=run.hypothesis.role,
                accepted=run.hypothesis.agent_id in evaluation.accepted_agent_ids,
                tool_calls=run.tool_calls,
                input_tokens=run.usage.input_tokens,
                output_tokens=run.usage.output_tokens,
                latency_seconds=run.latency_seconds,
                contribution=run.hypothesis.conclusion,
            )
            for run in all_runs
        ]
        all_usage = [
            state.get("supervisor_usage", {}),
            *state.get("preparation_usage", []),
            *(run.usage.model_dump(mode="json") for run in all_runs),
            *(row.get("usage", {}) for row in state["evaluations"]),
            response.usage.model_dump(mode="json"),
        ]
        scorecard = AgentScorecard(
            benchmark=state["benchmark"],
            case_id=state["case_id"],
            decision=evaluation.decision,
            repair_count=state.get("repair_count", 0),
            contributions=contributions,
            total_tool_calls=sum(item.tool_calls for item in contributions),
            total_tokens=sum(int(item.get("total_tokens") or 0) for item in all_usage),
            total_latency_seconds=round(
                sum(item.latency_seconds for item in contributions), 3
            ),
        )
        evidence: list[EvidenceReference] = []
        seen: set[str] = set()
        for run in latest_runs:
            for item in [
                *run.hypothesis.supporting_evidence,
                *run.hypothesis.counterevidence,
            ]:
                if item.evidence_id not in seen:
                    seen.add(item.evidence_id)
                    evidence.append(item)
        point_in_time = state["controlled_context"].get("point_in_time", {})
        risks: list[RiskFinding] = []
        if state["benchmark"] == "risk_demo":
            risks = build_risk_findings(
                latest_runs, evaluation, state["controlled_context"]
            )
        artifact = RiskAssessmentArtifact(
            benchmark=state["benchmark"],
            case_id=state["case_id"],
            subject_id=str(point_in_time.get("issuer_id", "")),
            report_period=str(point_in_time.get("report_period", "")),
            as_of_date=str(point_in_time.get("as_of_date", "")),
            data_snapshot_id=str(point_in_time.get("data_snapshot_id", "")),
            answer=answer.answer,
            scale=answer.scale,
            program=answer.program,
            evidence=evidence,
            risks=risks,
            limitations=evaluation.missing_evidence,
            evaluation=evaluation,
            scorecard=scorecard,
        )
        return {
            "final_answer": answer.model_dump(mode="json"),
            "artifact": artifact.model_dump(mode="json"),
            "node_trace": ["synthesize"],
        }

    async def run(
        self,
        *,
        benchmark: str,
        case_id: str,
        question: str,
        controlled_context: dict[str, Any],
        task_metadata: dict[str, Any] | None = None,
        preparation_tool_calls: int = 0,
        preparation_usage: list[dict[str, Any]] | None = None,
    ) -> TeamGraphState:
        return await self.graph.ainvoke(
            TeamGraphState(
                benchmark=benchmark,
                case_id=case_id,
                question=question,
                task_metadata=task_metadata or {},
                controlled_context=controlled_context,
                preparation_tool_calls=preparation_tool_calls,
                preparation_usage=preparation_usage or [],
                agent_runs=[],
                evaluations=[],
                repair_count=0,
                node_trace=[],
            )
        )
