from __future__ import annotations

import json
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import (
    AnalysisPlan,
    Evidence,
    QuerySpec,
    ToolResult,
)
from financial_research_agent.orchestration.evidence_builder import EvidenceBuilder
from financial_research_agent.orchestration.executor import PlanExecutor
from financial_research_agent.orchestration.interpreter import QueryInterpreter
from financial_research_agent.orchestration.planner import StructuredPlanner
from financial_research_agent.orchestration.validator import PlanValidator


class SpikeGraphState(TypedDict, total=False):
    run_id: str
    thread_id: str
    attempt_id: str
    question: str
    stage: str
    query_spec: dict[str, Any] | None
    plan: dict[str, Any] | None
    planner_source: str | None
    tool_results: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    report_preview: dict[str, Any] | None
    errors: list[dict[str, Any]]
    tool_execution_approved: bool | None


def initial_spike_state(question: str, run_id: str | None = None) -> SpikeGraphState:
    resolved_run_id = run_id or uuid4().hex
    return SpikeGraphState(
        run_id=resolved_run_id,
        thread_id=resolved_run_id,
        attempt_id=f"{resolved_run_id}:1",
        question=question,
        stage="created",
        query_spec=None,
        plan=None,
        planner_source=None,
        tool_results=[],
        evidence=[],
        report_preview=None,
        errors=[],
        tool_execution_approved=None,
    )


def graph_config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def ensure_json_safe_state(value: Any) -> None:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"STATE_SERIALIZATION_ERROR:{exc}") from exc


class LangGraphSpike:
    """A sidecar graph used only to validate phase-two compatibility."""

    def __init__(
        self,
        settings: Settings,
        interpreter: QueryInterpreter,
        planner: StructuredPlanner,
        validator: PlanValidator,
        executor: PlanExecutor,
    ) -> None:
        self.settings = settings
        self.interpreter = interpreter
        self.planner = planner
        self.validator = validator
        self.executor = executor
        self.evidence_builder = EvidenceBuilder()

    def build(self, checkpointer: Any, *, require_tool_approval: bool = False) -> Any:
        builder = StateGraph(SpikeGraphState)
        builder.add_node("interpret", self.interpret)
        builder.add_node("plan", self.plan)
        builder.add_node("validate_plan", self.validate_plan)
        builder.add_node("execute_tools", self.execute_tools)
        builder.add_node("build_evidence", self.build_evidence)
        builder.add_node("build_report_preview", self.build_report_preview)
        builder.add_edge(START, "interpret")
        builder.add_edge("interpret", "plan")
        builder.add_edge("plan", "validate_plan")

        if require_tool_approval:
            builder.add_node("review_tool_execution", self.review_tool_execution)
            builder.add_node("reject_tool_execution", self.reject_tool_execution)
            builder.add_edge("validate_plan", "review_tool_execution")
            builder.add_conditional_edges(
                "review_tool_execution",
                self.route_after_review,
                {
                    "approved": "execute_tools",
                    "rejected": "reject_tool_execution",
                },
            )
            builder.add_edge("reject_tool_execution", END)
        else:
            builder.add_edge("validate_plan", "execute_tools")

        builder.add_edge("execute_tools", "build_evidence")
        builder.add_edge("build_evidence", "build_report_preview")
        builder.add_edge("build_report_preview", END)
        return builder.compile(checkpointer=checkpointer)

    def interpret(self, state: SpikeGraphState) -> SpikeGraphState:
        query = self.interpreter.interpret(state["question"])
        return SpikeGraphState(
            stage="interpreted",
            query_spec=query.model_dump(mode="json"),
        )

    async def plan(self, state: SpikeGraphState) -> SpikeGraphState:
        query = QuerySpec.model_validate(state["query_spec"])
        plan, source = await self.planner.create_plan(state["question"], query)
        return SpikeGraphState(
            stage="planned",
            plan=plan.model_dump(mode="json"),
            planner_source=source,
        )

    def validate_plan(self, state: SpikeGraphState) -> SpikeGraphState:
        query = QuerySpec.model_validate(state["query_spec"])
        plan = AnalysisPlan.model_validate(state["plan"])
        self.validator.validate(plan, expected_query=query)
        return SpikeGraphState(stage="plan_validated")

    def review_tool_execution(self, state: SpikeGraphState) -> SpikeGraphState:
        plan = AnalysisPlan.model_validate(state["plan"])
        approved = interrupt(
            {
                "kind": "tool_execution_approval",
                "run_id": state["run_id"],
                "tools": [task.tool_name.value for task in plan.tasks],
            }
        )
        return SpikeGraphState(
            stage="tool_execution_reviewed",
            tool_execution_approved=approved is True,
        )

    @staticmethod
    def route_after_review(state: SpikeGraphState) -> str:
        return "approved" if state.get("tool_execution_approved") else "rejected"

    @staticmethod
    def reject_tool_execution(state: SpikeGraphState) -> SpikeGraphState:
        return SpikeGraphState(
            stage="rejected",
            errors=[
                *state.get("errors", []),
                {
                    "code": "INTERRUPT_REJECTED",
                    "node": "review_tool_execution",
                    "retryable": False,
                    "message": "tool execution was rejected",
                },
            ],
        )

    async def execute_tools(self, state: SpikeGraphState) -> SpikeGraphState:
        plan = AnalysisPlan.model_validate(state["plan"])
        results = await self.executor.execute(plan)
        errors = [
            {
                "code": result.error_code or "TOOL_EXECUTION_ERROR",
                "node": "execute_tools",
                "retryable": False,
                "message": result.error_message or "tool execution failed",
            }
            for result in results
            if not result.success
        ]
        return SpikeGraphState(
            stage="tools_executed",
            tool_results=[result.model_dump(mode="json") for result in results],
            errors=[*state.get("errors", []), *errors],
        )

    def build_evidence(self, state: SpikeGraphState) -> SpikeGraphState:
        results = [ToolResult.model_validate(item) for item in state["tool_results"]]
        evidence = self.evidence_builder.build(
            state["run_id"],
            results,
            self.settings.max_evidence,
        )
        return SpikeGraphState(
            stage="evidence_built",
            evidence=[item.model_dump(mode="json") for item in evidence],
        )

    @staticmethod
    def build_report_preview(state: SpikeGraphState) -> SpikeGraphState:
        query = QuerySpec.model_validate(state["query_spec"])
        evidence = [Evidence.model_validate(item) for item in state["evidence"]]
        completed = bool(evidence)
        return SpikeGraphState(
            stage="completed" if completed else "failed",
            report_preview={
                "subjects": query.stock_codes,
                "summary": f"LangGraph Spike validated {len(evidence)} evidence item(s).",
                "evidence_ids": [item.evidence_id for item in evidence],
                "production_report": False,
            },
        )
