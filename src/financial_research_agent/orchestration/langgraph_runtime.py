from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from financial_research_agent.analysis.models import EvidenceSufficiency
from financial_research_agent.analysis.sufficiency import EvidenceSufficiencyChecker
from financial_research_agent.config import Settings
from financial_research_agent.domain.models import (
    AnalysisPlan,
    AnalysisTask,
    Evidence,
    ExecutionMetadata,
    QuerySpec,
    ResearchReport,
    SemanticAlignmentResult,
    ToolResult,
    ToolName,
    ValidationResult,
)
from financial_research_agent.governance.models import (
    BudgetLimits,
    CompletionResult,
)
from financial_research_agent.governance.store import (
    BudgetConflict,
    BudgetExceeded,
)
from financial_research_agent.integrations.langchain.messages import (
    ai_message_dict,
    human_message_dict,
)
from financial_research_agent.memory.context import ContextBuilder, ContextStore
from financial_research_agent.memory.manager import MemoryManager
from financial_research_agent.memory.models import (
    BuiltContext,
    MemoryRecord,
    MemoryScope,
)
from financial_research_agent.orchestration.context import (
    OrchestrationResult,
    RunStage,
    StageTiming,
)
from financial_research_agent.orchestration.evidence_builder import EvidenceBuilder
from financial_research_agent.orchestration.factory import build_orchestration_service
from financial_research_agent.reporting.context import build_report_context
from financial_research_agent.reporting.factory import build_reporting_service
from financial_research_agent.reporting.service import ReportingResult
from financial_research_agent.reporting.validators import (
    bind_report_data_as_of,
    bind_report_scope,
    evidence_data_as_of,
)
from financial_research_agent.research import ResearchRunResult
from financial_research_agent.skills.models import SkillSelection, SkillStatus
from financial_research_agent.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResearchRuntimeContext:
    """Per-invocation identity kept outside checkpointed business state."""

    tenant_id: str
    user_id: str
    session_id: str
    run_id: str


class ResearchGraphState(TypedDict, total=False):
    run_id: str
    thread_id: str
    question: str
    resolved_question: str
    tenant_id: str
    user_id: str
    session_id: str
    messages: list[dict[str, Any]]
    memory_context: list[dict[str, Any]]
    knowledge_context: list[dict[str, Any]]
    memory_warnings: list[str]
    context_manifests: dict[str, dict[str, Any]]
    orchestration_stage: str
    reporting_status: str | None
    query_spec: dict[str, Any] | None
    semantic_alignment: dict[str, Any] | None
    execution_metadata: dict[str, Any] | None
    skill_selection: dict[str, Any] | None
    policy_version: str | None
    budget_snapshot: dict[str, Any] | None
    completion: dict[str, Any] | None
    plan: dict[str, Any] | None
    supplemental_plan: dict[str, Any] | None
    planner_source: str | None
    tool_results: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    evidence_sufficiency: dict[str, Any] | None
    replan_count: int
    action_hashes: list[str]
    termination_reason: str | None
    evidence_count_before_replan: int
    draft_report: dict[str, Any] | None
    final_report: dict[str, Any] | None
    validation: dict[str, Any] | None
    report_attempts: int
    orchestration_timings: list[dict[str, Any]]
    reporting_timings: dict[str, int]
    errors: list[str]
    reporting_errors: list[str]
    node_trace: list[str]
    terminal_writes: int


def initial_research_state(
    question: str,
    run_id: str | None = None,
    *,
    tenant_id: str = "local",
    user_id: str = "local",
    session_id: str = "default",
) -> ResearchGraphState:
    resolved_run_id = run_id or uuid4().hex
    return ResearchGraphState(
        run_id=resolved_run_id,
        thread_id=resolved_run_id,
        question=question,
        resolved_question=question,
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        messages=[human_message_dict(question)],
        memory_context=[],
        knowledge_context=[],
        memory_warnings=[],
        context_manifests={},
        orchestration_stage=RunStage.CREATED.value,
        reporting_status=None,
        query_spec=None,
        semantic_alignment=None,
        execution_metadata={"executed_at": datetime.now(timezone.utc).isoformat()},
        skill_selection=None,
        policy_version=None,
        budget_snapshot=None,
        completion=None,
        plan=None,
        supplemental_plan=None,
        planner_source=None,
        tool_results=[],
        evidence=[],
        evidence_sufficiency=None,
        replan_count=0,
        action_hashes=[],
        termination_reason=None,
        evidence_count_before_replan=0,
        draft_report=None,
        final_report=None,
        validation=None,
        report_attempts=0,
        orchestration_timings=[],
        reporting_timings={},
        errors=[],
        reporting_errors=[],
        node_trace=[],
        terminal_writes=0,
    )


def research_graph_config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def ensure_json_safe_graph_state(value: Any) -> None:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"STATE_SERIALIZATION_ERROR:{exc}") from exc


class LangGraphResearchService:
    """StateGraph mapping of the phase-one research path.

    Business validation, controlled tools, retry policy, evidence construction and
    report validation are deliberately reused. The graph owns state transitions and
    terminal routing, while the existing executor still owns dependency-aware tool
    concurrency.
    """

    def __init__(
        self,
        settings: Settings,
        orchestration=None,
        reporting=None,
        checkpointer: Any | None = None,
        business_store: Any | None = None,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.orchestration = orchestration or build_orchestration_service(settings)
        self.reporting = reporting or build_reporting_service(settings)
        self.evidence_builder = EvidenceBuilder()
        self.evidence_sufficiency_checker = EvidenceSufficiencyChecker()
        self.business_store = business_store
        self.skill_registry = skill_registry or SkillRegistry.from_builtin_catalog()
        self.skill_store = None
        self.governance_store = None
        self.policy_engine = None
        self.model_gateway = None
        self.tool_gateway = None
        self.completion_checker = None
        self.memory_manager = None
        self.knowledge_store = None
        self.context_builder = None
        self.context_store = None
        self.langgraph_store = None
        if business_store is not None and hasattr(business_store, "sessions"):
            from financial_research_agent.skills.store import SkillStore

            self.skill_store = SkillStore(business_store.sessions)
            self._configure_governance()
        self._checkpointer_context = None
        self._initialization_lock = asyncio.Lock()
        if checkpointer is not None:
            self.checkpointer = checkpointer
            self.graph = self._build_graph()
        elif settings.checkpoint_backend == "memory":
            self.checkpointer = InMemorySaver()
            self.graph = self._build_graph()
        else:
            self.checkpointer = None
            self.graph = None

    async def _ensure_runtime(self) -> None:
        if self.graph is not None:
            return
        async with self._initialization_lock:
            if self.graph is not None:
                return
            from financial_research_agent.persistence.checkpoint import (
                postgres_checkpointer,
            )
            from financial_research_agent.persistence.database import (
                create_business_engine,
                create_session_factory,
            )
            from financial_research_agent.persistence.store import BusinessStore

            self._checkpointer_context = postgres_checkpointer(self.settings)
            self.checkpointer = await self._checkpointer_context.__aenter__()
            if self.business_store is None:
                engine = create_business_engine(self.settings)
                self.business_store = BusinessStore(
                    engine,
                    create_session_factory(engine),
                    lease_seconds=self.settings.call_lease_seconds,
                )
            from financial_research_agent.skills.store import SkillStore

            self.skill_store = SkillStore(self.business_store.sessions)
            if self.settings.skills_enabled:
                builtin = SkillRegistry.from_builtin_catalog()
                await self.skill_store.bootstrap_builtins(builtin.versions())
                self.skill_registry = SkillRegistry(
                    await self.skill_store.definitions(status=SkillStatus.ACTIVE)
                )
            self._configure_governance()
            self.graph = self._build_graph()

    def _configure_governance(self) -> None:
        if self.business_store is None or self.governance_store is not None:
            return
        from financial_research_agent.governance.completion import (
            CompletionChecker,
        )
        from financial_research_agent.governance.gateways import (
            ModelGateway,
            ToolGateway,
        )
        from financial_research_agent.governance.policy import PolicyEngine
        from financial_research_agent.governance.store import GovernanceStore
        from financial_research_agent.providers.model import (
            OpenAICompatibleProvider,
        )

        self.governance_store = GovernanceStore(self.business_store.sessions)
        self.policy_engine = PolicyEngine(self.settings, self.governance_store)
        self.tool_gateway = ToolGateway(
            self.settings,
            self.orchestration.registry,
            self.business_store,
            self.governance_store,
            self.policy_engine,
        )
        provider = getattr(self.orchestration.planner, "provider", None)
        if isinstance(provider, OpenAICompatibleProvider):
            self.model_gateway = ModelGateway(
                self.settings,
                provider,
                self.business_store,
                self.governance_store,
                self.policy_engine,
            )
        self.completion_checker = CompletionChecker(
            self.governance_store,
            policy_version=self.settings.policy_version,
        )
        from financial_research_agent.knowledge.store import KnowledgeStore

        self.knowledge_store = KnowledgeStore(self.business_store.sessions)
        if not self.orchestration.registry.has("event_search"):
            from financial_research_agent.tools.event import EventSearchTool

            self.orchestration.registry.register(EventSearchTool(self.knowledge_store))
        if self.settings.memory_enabled:
            self.memory_manager = MemoryManager(
                self.business_store.sessions,
                session_ttl_seconds=(self.settings.session_memory_ttl_seconds),
                preference_ttl_seconds=(self.settings.preference_memory_ttl_seconds),
                episodic_ttl_seconds=(self.settings.episodic_memory_ttl_seconds),
            )
            self.context_builder = ContextBuilder(
                policy_version=self.settings.policy_version,
                model_summary_enabled=(self.settings.context_model_summary_enabled),
                compression_enabled=(self.settings.context_compression_enabled),
                summarizer=(self._summarize_context if self.model_gateway is not None else None),
            )
            self.context_store = ContextStore(
                self.business_store.sessions,
                model_name=self.settings.model_name or "unconfigured",
                prompt_version=self.settings.context_summary_prompt_version,
            )
            if self.settings.agent_framework == "langchain":
                from financial_research_agent.integrations.langchain.store import (
                    FinancialMemoryStore,
                )

                self.langgraph_store = FinancialMemoryStore(
                    self.memory_manager
                )

    async def _summarize_context(
        self,
        run_id: str,
        node_name: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if self.model_gateway is None:
            raise RuntimeError("CONTEXT_SUMMARY_GATEWAY_UNAVAILABLE")
        return await self.model_gateway.create_context_summary(
            run_id=run_id,
            target_node=node_name,
            context=context,
        )

    async def _knowledge_for_query(self, query: QuerySpec) -> list[dict[str, Any]]:
        if self.knowledge_store is None:
            return []
        events: list[dict[str, Any]] = []
        for symbol in query.stock_codes:
            rows = await self.knowledge_store.search_active(
                symbol=symbol,
                start_date=query.start_date,
                end_date=query.end_date,
                limit=8,
            )
            events.extend(item.model_dump(mode="json") for item in rows)
        return sorted(
            events,
            key=lambda item: (
                item["published_at"],
                -int(item["source_rank"]),
                item["event_id"],
            ),
            reverse=True,
        )[:12]

    async def aclose(self) -> None:
        if self.business_store is not None:
            await self.business_store.close()
            self.business_store = None
        if self._checkpointer_context is not None:
            await self._checkpointer_context.__aexit__(None, None, None)
            self._checkpointer_context = None

    def _build_graph(self):
        builder = StateGraph(
            ResearchGraphState,
            context_schema=ResearchRuntimeContext,
        )
        builder.add_node("load_memory", self._load_memory)
        builder.add_node("interpret", self._interpret)
        builder.add_node("align_semantics", self._align_semantics)
        builder.add_node("remember_query", self._remember_query)
        builder.add_node("select_skill", self._select_skill)
        builder.add_node("initialize_governance", self._initialize_governance)
        builder.add_node("plan", self._plan)
        builder.add_node("validate_plan", self._validate_plan)
        builder.add_node("execute_tools", self._execute_tools)
        builder.add_node("build_evidence", self._build_evidence)
        builder.add_node("check_evidence_sufficiency", self._check_evidence_sufficiency)
        builder.add_node("optional_replan", self._optional_replan)
        builder.add_node("generate_report", self._generate_report)
        builder.add_node("validate_report", self._validate_report)
        builder.add_node("revise_report", self._revise_report)
        builder.add_node("validate_revision", self._validate_revision)
        builder.add_node("completion_check", self._completion_check)
        builder.add_node("finalize", self._finalize)

        builder.add_edge(START, "load_memory")
        self._add_failure_edge(builder, "load_memory", "interpret")
        self._add_failure_edge(builder, "interpret", "align_semantics")
        self._add_failure_edge(builder, "align_semantics", "remember_query")
        self._add_failure_edge(builder, "remember_query", "select_skill")
        self._add_failure_edge(builder, "select_skill", "initialize_governance")
        self._add_failure_edge(builder, "initialize_governance", "plan")
        self._add_failure_edge(builder, "plan", "validate_plan")
        self._add_failure_edge(builder, "validate_plan", "execute_tools")
        self._add_failure_edge(builder, "execute_tools", "build_evidence")
        builder.add_edge("build_evidence", "check_evidence_sufficiency")
        builder.add_conditional_edges(
            "check_evidence_sufficiency",
            self._route_after_evidence_sufficiency,
            {
                "replan": "optional_replan",
                "report": "generate_report",
                "finalize": "completion_check",
            },
        )
        self._add_failure_edge(builder, "optional_replan", "execute_tools")
        builder.add_conditional_edges(
            "generate_report",
            self._route_after_generation,
            {"validate": "validate_report", "finalize": "completion_check"},
        )
        builder.add_conditional_edges(
            "validate_report",
            self._route_after_validation,
            {"revise": "revise_report", "finalize": "completion_check"},
        )
        builder.add_conditional_edges(
            "revise_report",
            self._route_after_generation,
            {"validate": "validate_revision", "finalize": "completion_check"},
        )
        builder.add_edge("validate_revision", "completion_check")
        builder.add_edge("completion_check", "finalize")
        builder.add_edge("finalize", END)
        return builder.compile(
            checkpointer=self.checkpointer,
            store=self.langgraph_store,
        )

    @staticmethod
    def _add_failure_edge(builder, source: str, success_target: str) -> None:
        builder.add_conditional_edges(
            source,
            lambda state: (
                "completion_check"
                if state.get("orchestration_stage") == RunStage.FAILED.value
                else "continue"
            ),
            {"continue": success_target, "completion_check": "completion_check"},
        )

    async def analyze(
        self,
        question: str,
        run_id: str | None = None,
        *,
        tenant_id: str = "local",
        user_id: str = "local",
        session_id: str = "default",
    ) -> ResearchRunResult:
        initial = initial_research_state(
            question,
            run_id,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
        )
        try:
            await self._ensure_runtime()
        except Exception as exc:
            return self._terminal_failure(
                initial["run_id"],
                f"PERSISTENCE_UNAVAILABLE:{type(exc).__name__}:{exc}",
            )
        graph_input: ResearchGraphState | None = initial
        if self.business_store is not None:
            created = await self.business_store.create_run(
                initial["run_id"],
                initial["thread_id"],
                question,
                "langgraph",
                tenant_id=initial["tenant_id"],
                user_id=initial["user_id"],
                session_id=initial["session_id"],
            )
            if not created:
                terminal = await self.business_store.get_terminal(initial["run_id"])
                if terminal is not None:
                    return ResearchRunResult.model_validate(terminal.result_payload)
                graph_input = None
        try:
            async with asyncio.timeout(self.settings.run_timeout_seconds):
                state = await self.graph.ainvoke(
                    graph_input,
                    research_graph_config(initial["thread_id"]),
                    context=ResearchRuntimeContext(
                        tenant_id=initial["tenant_id"],
                        user_id=initial["user_id"],
                        session_id=initial["session_id"],
                        run_id=initial["run_id"],
                    ),
                )
        except TimeoutError:
            result = self._terminal_failure(initial["run_id"], "RUN_TIMEOUT")
            await self._persist_interruption(initial["run_id"], "RUN_TIMEOUT")
            return result
        except Exception as exc:
            result = self._terminal_failure(initial["run_id"], f"{type(exc).__name__}:{exc}")
            await self._persist_interruption(initial["run_id"], f"{type(exc).__name__}:{exc}")
            return result
        ensure_json_safe_graph_state(state)
        result = self._to_result(state)
        await self._persist_checkpoint_reference(initial["run_id"])
        await self._persist_terminal(result)
        return result

    async def resume(self, run_id: str) -> ResearchRunResult:
        await self._ensure_runtime()
        runtime_context = None
        if self.business_store is not None:
            terminal = await self.business_store.get_terminal(run_id)
            if terminal is not None:
                return ResearchRunResult.model_validate(terminal.result_payload)
            record = await self.business_store.get_run(run_id)
            if record is None:
                raise ValueError("RUN_NOT_FOUND")
            runtime_context = ResearchRuntimeContext(
                tenant_id=record.tenant_id,
                user_id=record.user_id,
                session_id=record.session_id,
                run_id=record.id,
            )
        state = await self.graph.ainvoke(
            None,
            research_graph_config(run_id),
            context=runtime_context,
        )
        ensure_json_safe_graph_state(state)
        result = self._to_result(state)
        await self._persist_checkpoint_reference(run_id)
        await self._persist_terminal(result)
        return result

    async def request_cancel(self, run_id: str) -> bool:
        await self._ensure_runtime()
        if self.business_store is None:
            raise RuntimeError("CANCEL_REQUIRES_BUSINESS_STORE")
        return await self.business_store.request_cancel(run_id)

    async def _persist_checkpoint_reference(self, run_id: str) -> None:
        if self.business_store is None:
            return
        snapshot = await self.graph.aget_state(research_graph_config(run_id))
        checkpoint_id = snapshot.config.get("configurable", {}).get("checkpoint_id")
        await self.business_store.update_checkpoint(run_id, checkpoint_id)

    async def _persist_terminal(self, result: ResearchRunResult) -> None:
        if self.business_store is None:
            return
        await self.business_store.write_terminal(
            result.orchestration.run_id,
            "completed" if result.success else "failed",
            result.model_dump(mode="json"),
        )

    async def _persist_interruption(self, run_id: str, error: str) -> None:
        if self.business_store is None:
            return
        try:
            await self.business_store.mark_run_status(run_id, "interrupted")
            await self.business_store.append_event(
                run_id,
                "run_interrupted",
                payload={"error": error[:256]},
            )
        except Exception:
            logger.exception("failed to persist interruption for run_id=%s", run_id)

    @staticmethod
    def _memory_scope(state: ResearchGraphState) -> MemoryScope:
        return MemoryScope(
            tenant_id=state.get("tenant_id", "local"),
            user_id=state.get("user_id", "local"),
            session_id=state.get("session_id", "default"),
        )

    async def _record_context_manifest(
        self,
        state: ResearchGraphState,
        built: BuiltContext,
    ) -> dict[str, dict[str, Any]]:
        if self.context_store is not None:
            await self.context_store.persist(built.manifest, built.payload)
        manifests = dict(state.get("context_manifests", {}))
        manifests[built.manifest.node_name] = built.manifest.model_dump(mode="json")
        return manifests

    async def _build_context(
        self,
        method_name: str,
        **arguments: Any,
    ) -> BuiltContext:
        if self.context_builder is None:
            raise RuntimeError("CONTEXT_BUILDER_UNAVAILABLE")
        if self.settings.agent_framework == "langchain":
            from financial_research_agent.integrations.langchain.context import (
                context_builder_runnable,
            )

            runnable = context_builder_runnable(
                self.context_builder,
                method_name,
            )
            return await runnable.ainvoke(arguments)
        method = getattr(self.context_builder, method_name)
        return await method(**arguments)

    @staticmethod
    def _validate_runtime_scope(
        state: ResearchGraphState,
        runtime: Runtime[ResearchRuntimeContext],
    ) -> None:
        context = runtime.context
        if context is None:
            return
        state_scope = (
            state.get("tenant_id", "local"),
            state.get("user_id", "local"),
            state.get("session_id", "default"),
            state["run_id"],
        )
        runtime_scope = (
            context.tenant_id,
            context.user_id,
            context.session_id,
            context.run_id,
        )
        if state_scope != runtime_scope:
            raise PermissionError("RUNTIME_CONTEXT_SCOPE_MISMATCH")

    async def _load_memory(
        self,
        state: ResearchGraphState,
        runtime: Runtime[ResearchRuntimeContext],
    ) -> ResearchGraphState:
        attempt_id, cancelled = await self._start_node(state, "load_memory")
        if cancelled is not None:
            return cancelled
        started = time.perf_counter()
        try:
            self._validate_runtime_scope(state, runtime)
            records: list[MemoryRecord] = []
            if self.memory_manager is not None:
                records = await self.memory_manager.list(self._memory_scope(state))
            resolved, warnings = MemoryManager.resolve_question(state["question"], records)
            manifests = dict(state.get("context_manifests", {}))
            if self.context_builder is not None:
                built = await self._build_context(
                    "build_interpret",
                    run_id=state["run_id"],
                    question=resolved,
                    memory=records,
                )
                manifests = await self._record_context_manifest(state, built)
            update = self._orchestration_update(
                state,
                "load_memory",
                RunStage.LOADING_MEMORY,
                started,
                resolved_question=resolved,
                memory_context=[item.model_dump(mode="json") for item in records],
                memory_warnings=warnings,
                context_manifests=manifests,
            )
        except Exception as exc:
            update = self._orchestration_failure(state, "load_memory", started, exc)
        return await self._finish_node(attempt_id, update)

    async def _interpret(self, state: ResearchGraphState) -> ResearchGraphState:
        attempt_id, cancelled = await self._start_node(state, "interpret")
        if cancelled is not None:
            return cancelled
        started = time.perf_counter()
        try:
            query = self.orchestration.interpreter.interpret(
                state.get("resolved_question") or state["question"]
            )
            update = self._orchestration_update(
                state,
                "interpret",
                RunStage.INTERPRETING,
                started,
                query_spec=query.model_dump(mode="json"),
                execution_metadata=ExecutionMetadata(
                    executed_at=(state.get("execution_metadata") or {}).get(
                        "executed_at", datetime.now(timezone.utc)
                    ),
                    business_reference_date=self.orchestration.interpreter.today,
                    timezone=self.orchestration.interpreter.timezone_name,
                ).model_dump(mode="json"),
            )
        except Exception as exc:
            update = self._orchestration_failure(state, "interpret", started, exc)
        return await self._finish_node(attempt_id, update)

    async def _align_semantics(
        self, state: ResearchGraphState
    ) -> ResearchGraphState:
        attempt_id, cancelled = await self._start_node(state, "align_semantics")
        if cancelled is not None:
            return cancelled
        started = time.perf_counter()
        try:
            alignment = self.orchestration.semantic_validator.validate(
                state.get("resolved_question") or state["question"],
                QuerySpec.model_validate(state["query_spec"]),
            )
            result_stage = None if alignment.passed else RunStage.FAILED
            update = self._orchestration_update(
                state,
                "align_semantics",
                RunStage.ALIGNING_SEMANTICS,
                started,
                result_stage=result_stage,
                semantic_alignment=alignment.model_dump(mode="json"),
                errors=(
                    state.get("errors", [])
                    if alignment.passed
                    else [
                        *state.get("errors", []),
                        "SEMANTIC_ALIGNMENT_FAILED:"
                        + ",".join(alignment.errors),
                    ]
                ),
            )
        except Exception as exc:
            update = self._orchestration_failure(
                state, "align_semantics", started, exc
            )
        return await self._finish_node(attempt_id, update)

    async def _remember_query(self, state: ResearchGraphState) -> ResearchGraphState:
        attempt_id, cancelled = await self._start_node(state, "remember_query")
        if cancelled is not None:
            return cancelled
        started = time.perf_counter()
        try:
            records = [
                MemoryRecord.model_validate(item) for item in state.get("memory_context", [])
            ]
            if self.memory_manager is not None:
                await self.memory_manager.remember_query(
                    self._memory_scope(state),
                    QuerySpec.model_validate(state["query_spec"]),
                    run_id=state["run_id"],
                )
                records = await self.memory_manager.list(
                    self._memory_scope(state), audit_read=False
                )
            update = self._orchestration_update(
                state,
                "remember_query",
                RunStage.REMEMBERING,
                started,
                memory_context=[item.model_dump(mode="json") for item in records],
            )
        except Exception as exc:
            update = self._orchestration_failure(state, "remember_query", started, exc)
        return await self._finish_node(attempt_id, update)

    async def _select_skill(self, state: ResearchGraphState) -> ResearchGraphState:
        attempt_id, cancelled = await self._start_node(state, "select_skill")
        if cancelled is not None:
            return cancelled
        started = time.perf_counter()
        try:
            query = QuerySpec.model_validate(state["query_spec"])
            manifests = dict(state.get("context_manifests", {}))
            if self.context_builder is not None:
                built = await self._build_context(
                    "build_selection",
                    run_id=state["run_id"],
                    query=query,
                    candidate_skill_ids=[
                        item.version_id
                        for item in self.skill_registry.versions()
                        if item.status == SkillStatus.ACTIVE
                    ],
                )
                manifests = await self._record_context_manifest(state, built)
            available_tools = {item["name"] for item in self.orchestration.registry.schemas()}
            if self.settings.skills_enabled:
                selection = self.skill_registry.select(query, available_tools)
            else:
                selection = SkillSelection(
                    reason="default_flow:skills_disabled",
                    effective_allowed_tools=sorted(available_tools),
                )
            if self.skill_store is not None:
                await self.skill_store.persist_run_snapshot(state["run_id"], selection)
            if self.business_store is not None:
                await self.business_store.append_event(
                    state["run_id"],
                    "skill_selected",
                    node_name="select_skill",
                    payload={
                        "skills": selection.selected_ids,
                        "reason": selection.reason,
                        "effective_allowed_tools": [
                            item.value for item in selection.effective_allowed_tools
                        ],
                    },
                )
            update = self._orchestration_update(
                state,
                "select_skill",
                RunStage.SELECTING_SKILL,
                started,
                skill_selection=selection.model_dump(mode="json"),
                context_manifests=manifests,
            )
        except Exception as exc:
            update = self._orchestration_failure(state, "select_skill", started, exc)
        return await self._finish_node(attempt_id, update)

    async def _initialize_governance(self, state: ResearchGraphState) -> ResearchGraphState:
        attempt_id, cancelled = await self._start_node(state, "initialize_governance")
        if cancelled is not None:
            return cancelled
        started = time.perf_counter()
        try:
            selection = SkillSelection.model_validate(state["skill_selection"])
            skill_limits = selection.workflow_constraints
            model_calls = self.settings.max_model_calls
            tool_calls = self.settings.max_tool_calls
            report_revisions = self.settings.max_report_revisions
            if selection.snapshots:
                model_calls = min(model_calls, skill_limits.max_model_calls)
                tool_calls = min(tool_calls, skill_limits.max_tool_calls)
                report_revisions = min(report_revisions, skill_limits.max_report_revisions)
            limits = BudgetLimits(
                model_calls=model_calls,
                model_attempts=min(
                    self.settings.max_model_attempts,
                    model_calls * (self.settings.model_max_retries + 1),
                ),
                tool_calls=tool_calls,
                tool_attempts=min(
                    self.settings.max_tool_attempts,
                    tool_calls * (self.settings.max_tool_retries + 1),
                ),
                evidence=self.settings.max_evidence,
                report_revisions=report_revisions,
                replan=(
                    min(self.settings.max_replans, skill_limits.replan_limit)
                    if selection.snapshots
                    else 0
                ),
                tokens=self.settings.max_run_tokens,
                cost_microunits=self.settings.max_run_cost_microunits,
            )
            snapshot = None
            if self.governance_store is not None:
                snapshot = await self.governance_store.initialize_budget(
                    state["run_id"],
                    limits,
                    policy_version=self.settings.policy_version,
                )
            update = self._orchestration_update(
                state,
                "initialize_governance",
                RunStage.INITIALIZING_GOVERNANCE,
                started,
                policy_version=self.settings.policy_version,
                budget_snapshot=(snapshot.model_dump(mode="json") if snapshot else None),
            )
        except Exception as exc:
            update = self._orchestration_failure(state, "initialize_governance", started, exc)
        return await self._finish_node(attempt_id, update)

    async def _plan(self, state: ResearchGraphState) -> ResearchGraphState:
        attempt_id, cancelled = await self._start_node(state, "plan")
        if cancelled is not None:
            return cancelled
        started = time.perf_counter()
        reservation = None
        try:
            query = QuerySpec.model_validate(state["query_spec"])
            question = state.get("resolved_question") or state["question"]
            manifests = dict(state.get("context_manifests", {}))
            planning_context = None
            planning_manifest_id = None
            selection = SkillSelection.model_validate(state["skill_selection"])
            intent_tools = {
                item.value
                for item in self.orchestration.validator.allowed_tools_for_query(query)
            }
            skill_tools = {item.value for item in selection.effective_allowed_tools}
            visible_tools = intent_tools & skill_tools
            tool_schemas = [
                schema
                for schema in self.orchestration.registry.schemas()
                if schema["name"] in visible_tools
            ]
            if self.context_builder is not None:
                knowledge = await self._knowledge_for_query(query)
                built = await self._build_context(
                    "build_plan",
                    run_id=state["run_id"],
                    question=question,
                    query=query,
                    selection=selection,
                    tool_schemas=tool_schemas,
                    budget=state.get("budget_snapshot"),
                    memory=[
                        MemoryRecord.model_validate(item)
                        for item in state.get("memory_context", [])
                    ],
                    knowledge=knowledge,
                )
                manifests = await self._record_context_manifest(state, built)
                planning_context = built.payload
                planning_manifest_id = built.manifest.manifest_id
            if self.settings.agent_framework == "langchain":
                from financial_research_agent.integrations.langchain.skills import (
                    skill_agent_context,
                )

                planning_context = {
                    **(planning_context or {}),
                    "agent_context": skill_agent_context(selection),
                }
            if self.model_gateway is not None:
                try:
                    raw = await self.model_gateway.create_plan(
                        run_id=state["run_id"],
                        question=question,
                        query=query,
                        tool_schemas=tool_schemas,
                        planning_context=planning_context,
                        context_manifest_id=planning_manifest_id,
                    )
                    plan = AnalysisPlan.model_validate(raw)
                    source = "model"
                except (BudgetExceeded, BudgetConflict, PermissionError):
                    raise
                except Exception:
                    plan = self.orchestration.planner.rule_planner.create_plan(query, question)
                    source = "rule_fallback"
            elif self.business_store is not None:
                request_payload = {
                    "question": state["question"],
                    "query": query.model_dump(mode="json"),
                    "prompt_version": self.settings.planner_prompt_version,
                }
                reservation = await self.business_store.reserve_model_call(
                    run_id=state["run_id"],
                    node_name="plan",
                    idempotency_key=f"{state['run_id']}:plan:model",
                    provider=self.settings.model_provider,
                    model_name=self.settings.model_name or "rule_fallback",
                    request_payload=request_payload,
                )
                if not reservation.execute:
                    plan = AnalysisPlan.model_validate(reservation.result_payload["plan"])
                    source = reservation.result_payload["planner_source"]
                else:
                    plan, source = await self.orchestration.planner.create_plan(question, query)
                    await self.business_store.complete_model_call(
                        reservation.call_id,
                        {
                            "plan": plan.model_dump(mode="json"),
                            "planner_source": source,
                        },
                    )
            else:
                plan, source = await self.orchestration.planner.create_plan(question, query)
            plan = self.orchestration.validator.normalize_for_execution(plan, question)
            update = self._orchestration_update(
                state,
                "plan",
                RunStage.PLANNING,
                started,
                plan=plan.model_dump(mode="json"),
                planner_source=source,
                context_manifests=manifests,
                knowledge_context=knowledge if self.context_builder is not None else [],
                messages=[
                    *state.get("messages", []),
                    ai_message_dict(
                        plan.model_dump(mode="json"),
                        phase="plan",
                        source=source,
                    ),
                ],
            )
        except Exception as exc:
            if reservation is not None and reservation.execute:
                await self.business_store.fail_model_call(
                    reservation.call_id, f"{type(exc).__name__}:{exc}"
                )
            update = self._orchestration_failure(state, "plan", started, exc)
        return await self._finish_node(attempt_id, update)

    async def _validate_plan(self, state: ResearchGraphState) -> ResearchGraphState:
        attempt_id, cancelled = await self._start_node(state, "validate_plan")
        if cancelled is not None:
            return cancelled
        started = time.perf_counter()
        try:
            query = QuerySpec.model_validate(state["query_spec"])
            plan = AnalysisPlan.model_validate(state["plan"])
            self.orchestration.validator.validate(plan, expected_query=query)
            selection = SkillSelection.model_validate(state["skill_selection"])
            self.skill_registry.validate_plan(
                selection, (task.tool_name.value for task in plan.tasks)
            )
            update = self._orchestration_update(
                state,
                "validate_plan",
                RunStage.VALIDATING_PLAN,
                started,
                action_hashes=[self._action_hash(task) for task in plan.tasks],
            )
        except Exception as exc:
            update = self._orchestration_failure(state, "validate_plan", started, exc)
        return await self._finish_node(attempt_id, update)

    async def _execute_tools(self, state: ResearchGraphState) -> ResearchGraphState:
        attempt_id, cancelled = await self._start_node(state, "execute_tools")
        if cancelled is not None:
            return cancelled
        started = time.perf_counter()
        try:
            plan_payload = (
                state.get("supplemental_plan")
                if state.get("replan_count", 0) > 0 and state.get("supplemental_plan")
                else state["plan"]
            )
            plan = AnalysisPlan.model_validate(plan_payload)
            tool_messages: list[dict[str, Any]] = []
            if self.tool_gateway is not None:
                selection = SkillSelection.model_validate(state["skill_selection"])
                if self.settings.agent_framework == "langchain":
                    (
                        results,
                        tool_messages,
                    ) = await self.tool_gateway.execute_with_messages(
                        run_id=state["run_id"],
                        plan=plan,
                        selection=selection,
                    )
                else:
                    results = await self.tool_gateway.execute(
                        run_id=state["run_id"],
                        plan=plan,
                        selection=selection,
                    )
            elif self.business_store is None:
                results = await self.orchestration.executor.execute(plan)
            else:
                from financial_research_agent.persistence.executor import (
                    PersistentPlanExecutor,
                )

                results = await PersistentPlanExecutor(
                    self.orchestration.executor, self.business_store
                ).execute(state["run_id"], plan)
            tool_errors = [
                f"{item.task_id}:{item.error_code}:{item.error_message}"
                for item in results
                if not item.success
            ]
            update = self._orchestration_update(
                state,
                "execute_tools",
                RunStage.EXECUTING,
                started,
                tool_results=[
                    *state.get("tool_results", []),
                    *[item.model_dump(mode="json") for item in results],
                ],
                errors=[*state.get("errors", []), *tool_errors],
                messages=[*state.get("messages", []), *tool_messages],
            )
        except Exception as exc:
            update = self._orchestration_failure(state, "execute_tools", started, exc)
        return await self._finish_node(attempt_id, update)

    async def _build_evidence(self, state: ResearchGraphState) -> ResearchGraphState:
        attempt_id, cancelled = await self._start_node(state, "build_evidence")
        if cancelled is not None:
            return cancelled
        started = time.perf_counter()
        evidence_budget = None
        try:
            results = [ToolResult.model_validate(item) for item in state["tool_results"]]
            evidence = self.evidence_builder.build(
                state["run_id"], results, self.settings.max_evidence
            )
            previous_ids = {
                item.get("evidence_id") for item in state.get("evidence", [])
            }
            new_evidence_count = sum(
                item.evidence_id not in previous_ids for item in evidence
            )
            if self.governance_store is not None and new_evidence_count:
                evidence_budget = await self.governance_store.reserve(
                    run_id=state["run_id"],
                    reservation_key=(
                        f"{state['run_id']}:build_evidence:"
                        f"pass:{state.get('replan_count', 0)}"
                    ),
                    resource="evidence",
                    amount=new_evidence_count,
                    metadata={"node": "build_evidence"},
                )
            update = self._orchestration_update(
                state,
                "build_evidence",
                RunStage.BUILDING_EVIDENCE,
                started,
                result_stage=RunStage.BUILDING_EVIDENCE,
                evidence=[item.model_dump(mode="json") for item in evidence],
                execution_metadata=(
                    ExecutionMetadata.model_validate(
                        state["execution_metadata"]
                    ).model_copy(
                        update={"data_as_of": evidence_data_as_of(evidence)}
                    ).model_dump(mode="json")
                ),
                errors=state.get("errors", []),
            )
            if evidence_budget is not None:
                await self.governance_store.commit(evidence_budget.entry_id)
        except Exception as exc:
            if evidence_budget is not None:
                await self.governance_store.release(evidence_budget.entry_id)
            update = self._orchestration_failure(state, "build_evidence", started, exc)
        return await self._finish_node(attempt_id, update)

    async def _check_evidence_sufficiency(
        self, state: ResearchGraphState
    ) -> ResearchGraphState:
        attempt_id, cancelled = await self._start_node(
            state, "check_evidence_sufficiency"
        )
        if cancelled is not None:
            return cancelled
        started = time.perf_counter()
        try:
            evidence = [Evidence.model_validate(item) for item in state.get("evidence", [])]
            selection = SkillSelection.model_validate(state["skill_selection"])
            sufficiency = self.evidence_sufficiency_checker.check(
                selection=selection,
                evidence=evidence,
                original_plan=AnalysisPlan.model_validate(state["plan"]),
                replan_count=state.get("replan_count", 0),
            )
            if (
                not sufficiency.passed
                and state.get("replan_count", 0) > 0
                and len(evidence) <= state.get("evidence_count_before_replan", 0)
            ):
                sufficiency = sufficiency.model_copy(
                    update={
                        "replan_allowed": False,
                        "no_progress": True,
                        "termination_reason": "REPLAN_NO_NEW_EVIDENCE",
                    }
                )
            if sufficiency.passed:
                result_stage = RunStage.COMPLETED
                errors = state.get("errors", [])
            elif sufficiency.replan_allowed:
                result_stage = RunStage.CHECKING_EVIDENCE
                errors = state.get("errors", [])
            else:
                result_stage = RunStage.FAILED
                errors = [
                    *state.get("errors", []),
                    *self.skill_registry.validate_evidence(
                        selection, (item.evidence_type for item in evidence)
                    ),
                    sufficiency.termination_reason or "EVIDENCE_INSUFFICIENT",
                ]
            update = self._orchestration_update(
                state,
                "check_evidence_sufficiency",
                RunStage.CHECKING_EVIDENCE,
                started,
                result_stage=result_stage,
                evidence_sufficiency=sufficiency.model_dump(mode="json"),
                termination_reason=sufficiency.termination_reason,
                errors=errors,
            )
        except Exception as exc:
            update = self._orchestration_failure(
                state, "check_evidence_sufficiency", started, exc
            )
        return await self._finish_node(attempt_id, update)

    async def _optional_replan(
        self, state: ResearchGraphState
    ) -> ResearchGraphState:
        attempt_id, cancelled = await self._start_node(state, "optional_replan")
        if cancelled is not None:
            return cancelled
        started = time.perf_counter()
        reservation = None
        try:
            sufficiency = EvidenceSufficiency.model_validate(
                state["evidence_sufficiency"]
            )
            if not sufficiency.replan_allowed:
                raise ValueError("REPLAN_NOT_AUTHORIZED_BY_EVIDENCE_GATE")
            query = QuerySpec.model_validate(state["query_spec"])
            selection = SkillSelection.model_validate(state["skill_selection"])
            allowed = {item.value for item in selection.effective_allowed_tools}
            action_hashes = list(state.get("action_hashes", []))
            tasks: list[AnalysisTask] = []
            next_count = state.get("replan_count", 0) + 1
            for index, missing in enumerate(sufficiency.missing):
                if not missing.candidate_tool or missing.candidate_tool not in allowed:
                    raise ValueError("REPLAN_TOOL_OUTSIDE_SKILL")
                tool_name = ToolName(missing.candidate_tool)
                tool = self.orchestration.registry.get(tool_name.value)
                validated = tool.validate_input(missing.safe_arguments)
                stock_code = getattr(validated, "stock_code", None)
                stock_codes = getattr(validated, "stock_codes", None)
                if stock_code and stock_code not in query.stock_codes:
                    raise ValueError("REPLAN_STOCK_SCOPE_EXPANDED")
                if stock_codes and not set(stock_codes).issubset(query.stock_codes):
                    raise ValueError("REPLAN_STOCK_SCOPE_EXPANDED")
                start_date = getattr(validated, "start_date", None)
                end_date = getattr(validated, "end_date", None)
                if query.start_date and start_date and start_date < query.start_date:
                    raise ValueError("REPLAN_DATE_SCOPE_EXPANDED")
                if query.end_date and end_date and end_date > query.end_date:
                    raise ValueError("REPLAN_DATE_SCOPE_EXPANDED")
                task = AnalysisTask(
                    task_id=f"{missing.evidence_type}_replan{next_count}_{index}",
                    tool_name=tool_name,
                    arguments=missing.safe_arguments,
                )
                action_hash = self._action_hash(task)
                if action_hash in action_hashes:
                    raise ValueError("REPLAN_DUPLICATE_ACTION")
                action_hashes.append(action_hash)
                tasks.append(task)
            supplemental = AnalysisPlan(
                query=query,
                tasks=tasks,
                expected_sections=[f"evidence_supplement_{next_count}"],
            )
            self.skill_registry.validate_plan(
                selection, (task.tool_name.value for task in tasks)
            )
            if self.governance_store is not None:
                reservation = await self.governance_store.reserve(
                    run_id=state["run_id"],
                    reservation_key=f"{state['run_id']}:optional_replan:{next_count}",
                    resource="replan",
                    metadata={
                        "node": "optional_replan",
                        "missing": [item.evidence_type for item in sufficiency.missing],
                    },
                )
                await self.governance_store.commit(reservation.entry_id)
            update = self._orchestration_update(
                state,
                "optional_replan",
                RunStage.REPLANNING,
                started,
                supplemental_plan=supplemental.model_dump(mode="json"),
                replan_count=next_count,
                action_hashes=action_hashes,
                evidence_count_before_replan=len(state.get("evidence", [])),
                termination_reason=None,
            )
        except Exception as exc:
            if reservation is not None and reservation.status == "reserved":
                await self.governance_store.release(reservation.entry_id)
            update = self._orchestration_failure(state, "optional_replan", started, exc)
        return await self._finish_node(attempt_id, update)

    async def _generate_report(self, state: ResearchGraphState) -> ResearchGraphState:
        attempt_id, cancelled = await self._start_node(state, "generate_report", report_node=True)
        if cancelled is not None:
            return cancelled
        started = time.perf_counter()
        timings = dict(state.get("reporting_timings", {}))
        reservation = None
        try:
            query = QuerySpec.model_validate(state["query_spec"])
            evidence = [Evidence.model_validate(item) for item in state["evidence"]]
            manifests = dict(state.get("context_manifests", {}))
            context_manifest_id = None
            if self.context_builder is not None:
                built = await self._build_context(
                    "build_report",
                    run_id=state["run_id"],
                    node_name="generate_report",
                    query=query,
                    evidence=evidence,
                    selection=SkillSelection.model_validate(state["skill_selection"]),
                    memory=[
                        MemoryRecord.model_validate(item)
                        for item in state.get("memory_context", [])
                    ],
                    knowledge=list(state.get("knowledge_context", [])),
                )
                report_context = built.payload
                manifests = await self._record_context_manifest(state, built)
                context_manifest_id = built.manifest.manifest_id
            else:
                report_context = build_report_context(
                    query,
                    evidence,
                    self.settings.max_report_context_chars,
                )
            if self.model_gateway is not None:
                raw = await self.model_gateway.create_report(
                    run_id=state["run_id"],
                    node_name="generate_report",
                    question=(state.get("resolved_question") or state["question"]),
                    report_context=report_context,
                    context_manifest_id=context_manifest_id,
                )
                report = ResearchReport.model_validate(raw)
            elif self.business_store is not None:
                reservation = await self.business_store.reserve_model_call(
                    run_id=state["run_id"],
                    node_name="generate_report",
                    idempotency_key=f"{state['run_id']}:generate_report:model",
                    provider=self.settings.model_provider,
                    model_name=self.settings.model_name,
                    request_payload={
                        "question": state["question"],
                        "query": query.model_dump(mode="json"),
                        "evidence": [item.model_dump(mode="json") for item in evidence],
                        "prompt_version": self.settings.report_prompt_version,
                    },
                )
            if self.model_gateway is not None:
                pass
            elif reservation is not None and not reservation.execute:
                report = ResearchReport.model_validate(reservation.result_payload["report"])
            else:
                report = await self.reporting.reporter.generate(state["question"], query, evidence)
                if reservation is not None:
                    await self.business_store.complete_model_call(
                        reservation.call_id,
                        {"report": report.model_dump(mode="json")},
                    )
            report = bind_report_scope(report, query)
            report = bind_report_data_as_of(report, evidence)
            timings["generate_report"] = self._elapsed_ms(started)
            update = ResearchGraphState(
                draft_report=report.model_dump(mode="json"),
                report_attempts=1,
                reporting_timings=timings,
                context_manifests=manifests,
                messages=[
                    *state.get("messages", []),
                    ai_message_dict(
                        report.model_dump(mode="json"),
                        phase="generate_report",
                    ),
                ],
                node_trace=[*state.get("node_trace", []), "generate_report"],
            )
        except Exception as exc:
            if reservation is not None and reservation.execute:
                await self.business_store.fail_model_call(
                    reservation.call_id, f"{type(exc).__name__}:{exc}"
                )
            timings["generate_report"] = self._elapsed_ms(started)
            update = ResearchGraphState(
                reporting_status="generation_failed",
                report_attempts=1,
                reporting_timings=timings,
                reporting_errors=[f"{type(exc).__name__}:{exc}"],
                node_trace=[*state.get("node_trace", []), "generate_report"],
            )
        return await self._finish_node(attempt_id, update)

    async def _validate_report(self, state: ResearchGraphState) -> ResearchGraphState:
        attempt_id, cancelled = await self._start_node(state, "validate_report", report_node=True)
        if cancelled is not None:
            return cancelled
        started = time.perf_counter()
        timings = dict(state.get("reporting_timings", {}))
        try:
            report = ResearchReport.model_validate(state["draft_report"])
            validation = self.reporting.validator.validate(
                report,
                QuerySpec.model_validate(state["query_spec"]),
                [Evidence.model_validate(item) for item in state["evidence"]],
                state["run_id"],
            )
            status = (
                "completed"
                if validation.passed
                else (
                    "validation_failed"
                    if self.settings.max_report_revisions == 0
                    else "revision_required"
                )
            )
            update = ResearchGraphState(
                final_report=(
                    report.model_dump(mode="json")
                    if status in {"completed", "validation_failed"}
                    else None
                ),
                validation=validation.model_dump(mode="json"),
                reporting_status=status,
                reporting_timings=timings,
                reporting_errors=(validation.errors if status == "validation_failed" else []),
                node_trace=[*state.get("node_trace", []), "validate_report"],
            )
        except Exception as exc:
            update = ResearchGraphState(
                reporting_status="generation_failed",
                reporting_timings=timings,
                reporting_errors=[f"{type(exc).__name__}:{exc}"],
                node_trace=[*state.get("node_trace", []), "validate_report"],
            )
        timings["validate_report"] = self._elapsed_ms(started)
        return await self._finish_node(attempt_id, update)

    async def _revise_report(self, state: ResearchGraphState) -> ResearchGraphState:
        attempt_id, cancelled = await self._start_node(state, "revise_report", report_node=True)
        if cancelled is not None:
            return cancelled
        started = time.perf_counter()
        timings = dict(state.get("reporting_timings", {}))
        validation = ValidationResult.model_validate(state["validation"])
        draft = ResearchReport.model_validate(state["draft_report"])
        reservation = None
        revision_budget = None
        try:
            query = QuerySpec.model_validate(state["query_spec"])
            evidence = [Evidence.model_validate(item) for item in state["evidence"]]
            manifests = dict(state.get("context_manifests", {}))
            context_manifest_id = None
            if self.context_builder is not None:
                built = await self._build_context(
                    "build_report",
                    run_id=state["run_id"],
                    node_name="revise_report",
                    query=query,
                    evidence=evidence,
                    selection=SkillSelection.model_validate(state["skill_selection"]),
                    memory=[
                        MemoryRecord.model_validate(item)
                        for item in state.get("memory_context", [])
                    ],
                    draft=draft.model_dump(mode="json"),
                    validation_errors=validation.errors,
                    knowledge=list(state.get("knowledge_context", [])),
                )
                report_context = built.payload
                manifests = await self._record_context_manifest(state, built)
                context_manifest_id = built.manifest.manifest_id
            else:
                report_context = build_report_context(
                    query,
                    evidence,
                    self.settings.max_report_context_chars,
                )
            if self.governance_store is not None:
                revision_budget = await self.governance_store.reserve(
                    run_id=state["run_id"],
                    reservation_key=f"{state['run_id']}:revise_report:revision",
                    resource="report_revisions",
                    metadata={"node": "revise_report"},
                )
            if self.model_gateway is not None:
                raw = await self.model_gateway.create_report(
                    run_id=state["run_id"],
                    node_name="revise_report",
                    question=(state.get("resolved_question") or state["question"]),
                    report_context=report_context,
                    draft=draft.model_dump(mode="json"),
                    validation_errors=validation.errors,
                    context_manifest_id=context_manifest_id,
                )
                revised = ResearchReport.model_validate(raw)
            elif self.business_store is not None:
                reservation = await self.business_store.reserve_model_call(
                    run_id=state["run_id"],
                    node_name="revise_report",
                    idempotency_key=f"{state['run_id']}:revise_report:model",
                    provider=self.settings.model_provider,
                    model_name=self.settings.model_name,
                    request_payload={
                        "question": state["question"],
                        "query": query.model_dump(mode="json"),
                        "evidence": [item.model_dump(mode="json") for item in evidence],
                        "draft": draft.model_dump(mode="json"),
                        "validation_errors": validation.errors,
                        "prompt_version": self.settings.report_prompt_version,
                    },
                )
            if self.model_gateway is not None:
                pass
            elif reservation is not None and not reservation.execute:
                revised = ResearchReport.model_validate(reservation.result_payload["report"])
            else:
                revised = await self.reporting.reporter.generate(
                    state["question"],
                    query,
                    evidence,
                    draft=draft,
                    validation_errors=validation.errors,
                )
                if reservation is not None:
                    await self.business_store.complete_model_call(
                        reservation.call_id,
                        {"report": revised.model_dump(mode="json")},
                    )
            revised = bind_report_scope(revised, query)
            revised = bind_report_data_as_of(revised, evidence)
            if revision_budget is not None:
                await self.governance_store.commit(revision_budget.entry_id)
            timings["revise_report"] = self._elapsed_ms(started)
            update = ResearchGraphState(
                draft_report=revised.model_dump(mode="json"),
                report_attempts=2,
                reporting_timings=timings,
                context_manifests=manifests,
                messages=[
                    *state.get("messages", []),
                    ai_message_dict(
                        revised.model_dump(mode="json"),
                        phase="revise_report",
                    ),
                ],
                node_trace=[*state.get("node_trace", []), "revise_report"],
            )
        except Exception as exc:
            if revision_budget is not None:
                await self.governance_store.release(revision_budget.entry_id)
            if reservation is not None and reservation.execute:
                await self.business_store.fail_model_call(
                    reservation.call_id, f"{type(exc).__name__}:{exc}"
                )
            timings["revise_report"] = self._elapsed_ms(started)
            update = ResearchGraphState(
                final_report=draft.model_dump(mode="json"),
                reporting_status="generation_failed",
                report_attempts=2,
                reporting_timings=timings,
                reporting_errors=[
                    *validation.errors,
                    f"{type(exc).__name__}:{exc}",
                ],
                node_trace=[*state.get("node_trace", []), "revise_report"],
            )
        return await self._finish_node(attempt_id, update)

    async def _validate_revision(self, state: ResearchGraphState) -> ResearchGraphState:
        attempt_id, cancelled = await self._start_node(state, "validate_revision", report_node=True)
        if cancelled is not None:
            return cancelled
        started = time.perf_counter()
        timings = dict(state.get("reporting_timings", {}))
        try:
            report = ResearchReport.model_validate(state["draft_report"])
            validation = self.reporting.validator.validate(
                report,
                QuerySpec.model_validate(state["query_spec"]),
                [Evidence.model_validate(item) for item in state["evidence"]],
                state["run_id"],
            )
            update = ResearchGraphState(
                final_report=report.model_dump(mode="json"),
                validation=validation.model_dump(mode="json"),
                reporting_status=("completed" if validation.passed else "validation_failed"),
                reporting_timings=timings,
                reporting_errors=[] if validation.passed else validation.errors,
                node_trace=[*state.get("node_trace", []), "validate_revision"],
            )
        except Exception as exc:
            update = ResearchGraphState(
                reporting_status="generation_failed",
                reporting_timings=timings,
                reporting_errors=[f"{type(exc).__name__}:{exc}"],
                node_trace=[*state.get("node_trace", []), "validate_revision"],
            )
        timings["validate_revision"] = self._elapsed_ms(started)
        return await self._finish_node(attempt_id, update)

    async def _completion_check(self, state: ResearchGraphState) -> ResearchGraphState:
        attempt_id, _ = await self._start_node(state, "completion_check", allow_cancel=False)
        started = time.perf_counter()
        try:
            if self.completion_checker is None:
                completion = CompletionResult(
                    passed=True,
                    policy_version=self.settings.policy_version,
                )
            else:
                completion = await self.completion_checker.check(dict(state))
            stage = RunStage(state["orchestration_stage"])
            errors = list(state.get("errors", []))
            if not completion.passed:
                stage = RunStage.FAILED
                errors.extend(completion.errors)
            update = self._orchestration_update(
                state,
                "completion_check",
                RunStage.COMPLETING,
                started,
                result_stage=stage,
                completion=completion.model_dump(mode="json"),
                budget_snapshot=(
                    completion.budget.model_dump(mode="json")
                    if completion.budget is not None
                    else state.get("budget_snapshot")
                ),
                errors=errors,
            )
        except Exception as exc:
            update = self._orchestration_failure(state, "completion_check", started, exc)
        return await self._finish_node(attempt_id, update)

    @staticmethod
    def _route_after_evidence_sufficiency(state: ResearchGraphState) -> str:
        sufficiency = state.get("evidence_sufficiency") or {}
        if state.get("orchestration_stage") == RunStage.FAILED.value:
            return "finalize"
        if sufficiency.get("replan_allowed"):
            return "replan"
        return "report" if sufficiency.get("passed") else "finalize"

    @staticmethod
    def _route_after_generation(state: ResearchGraphState) -> str:
        return "finalize" if state.get("reporting_status") == "generation_failed" else "validate"

    @staticmethod
    def _route_after_validation(state: ResearchGraphState) -> str:
        return "revise" if state.get("reporting_status") == "revision_required" else "finalize"

    async def _finalize(self, state: ResearchGraphState) -> ResearchGraphState:
        attempt_id, _ = await self._start_node(state, "finalize", allow_cancel=False)
        writes = state.get("terminal_writes", 0)
        if writes:
            raise RuntimeError("TERMINAL_STATE_ALREADY_WRITTEN")
        memory_warnings = list(state.get("memory_warnings", []))
        validation = state.get("validation") or {}
        completion = state.get("completion") or {}
        if (
            self.memory_manager is not None
            and validation.get("passed") is True
            and completion.get("passed") is True
            and state.get("reporting_status") == "completed"
            and state.get("final_report") is not None
        ):
            try:
                query = QuerySpec.model_validate(state["query_spec"])
                report = ResearchReport.model_validate(state["final_report"])
                await self.memory_manager.reflect(
                    self._memory_scope(state),
                    run_id=state["run_id"],
                    task_type=query.intent.value,
                    payload={
                        "subjects": report.subjects,
                        "summary": report.summary,
                        "data_as_of": (
                            report.data_as_of.isoformat() if report.data_as_of else None
                        ),
                        "tool_failures": [
                            {
                                "task_id": item.get("task_id"),
                                "error_code": item.get("error_code"),
                            }
                            for item in state.get("tool_results", [])
                            if not item.get("success")
                        ],
                        "historical_only": True,
                    },
                    validation_passed=True,
                    skill_versions=[
                        item.get("version_id")
                        for item in (state.get("skill_selection") or {}).get(
                            "snapshots", []
                        )
                        if item.get("version_id")
                    ],
                    model_version=self.settings.model_name,
                )
            except Exception as exc:
                memory_warnings.append(
                    f"EPISODIC_REFLECTION_SKIPPED:{type(exc).__name__}"
                )
        update = ResearchGraphState(
            terminal_writes=1,
            memory_warnings=memory_warnings,
            node_trace=[*state.get("node_trace", []), "finalize"],
        )
        return await self._finish_node(attempt_id, update)

    def _orchestration_update(
        self,
        state: ResearchGraphState,
        node: str,
        stage: RunStage,
        started: float,
        result_stage: RunStage | None = None,
        **updates: Any,
    ) -> ResearchGraphState:
        timings = [
            *state.get("orchestration_timings", []),
            {"stage": stage.value, "duration_ms": self._elapsed_ms(started)},
        ]
        return ResearchGraphState(
            orchestration_stage=(result_stage or stage).value,
            orchestration_timings=timings,
            node_trace=[*state.get("node_trace", []), node],
            **updates,
        )

    def _orchestration_failure(
        self,
        state: ResearchGraphState,
        node: str,
        started: float,
        exc: Exception,
    ) -> ResearchGraphState:
        return self._orchestration_update(
            state,
            node,
            RunStage.FAILED,
            started,
            errors=[*state.get("errors", []), f"{type(exc).__name__}:{exc}"],
        )

    async def _start_node(
        self,
        state: ResearchGraphState,
        node_name: str,
        *,
        report_node: bool = False,
        allow_cancel: bool = True,
    ) -> tuple[str | None, ResearchGraphState | None]:
        if self.business_store is None:
            return None, None
        attempt_id = await self.business_store.start_attempt(state["run_id"], node_name)
        if allow_cancel and await self.business_store.is_cancel_requested(state["run_id"]):
            await self.business_store.finish_attempt(
                attempt_id, status="cancelled", error_code="RUN_CANCELLED"
            )
            trace = [*state.get("node_trace", []), node_name]
            if report_node or state.get("orchestration_stage") == RunStage.COMPLETED.value:
                return attempt_id, ResearchGraphState(
                    reporting_status="generation_failed",
                    reporting_errors=["RUN_CANCELLED"],
                    node_trace=trace,
                )
            return attempt_id, ResearchGraphState(
                orchestration_stage=RunStage.FAILED.value,
                errors=[*state.get("errors", []), "RUN_CANCELLED"],
                node_trace=trace,
            )
        return attempt_id, None

    async def _finish_node(
        self,
        attempt_id: str | None,
        update: ResearchGraphState,
    ) -> ResearchGraphState:
        if self.business_store is None or attempt_id is None:
            return update
        failed = update.get("orchestration_stage") == RunStage.FAILED.value or update.get(
            "reporting_status"
        ) in {
            "generation_failed",
            "validation_failed",
        }
        error_code = None
        if failed:
            errors = update.get("reporting_errors") or update.get("errors") or []
            error_code = errors[0][:128] if errors else "NODE_FAILED"
        await self.business_store.finish_attempt(
            attempt_id,
            status="failed" if failed else "completed",
            error_code=error_code,
        )
        return update

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

    @staticmethod
    def _action_hash(task: AnalysisTask) -> str:
        payload = {
            "tool_name": task.tool_name.value,
            "arguments": task.arguments,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _to_result(state: ResearchGraphState) -> ResearchRunResult:
        skill_selection = (
            SkillSelection.model_validate(state["skill_selection"])
            if state.get("skill_selection")
            else None
        )
        orchestration = OrchestrationResult(
            run_id=state["run_id"],
            success=state["orchestration_stage"] == RunStage.COMPLETED.value,
            stage=RunStage(state["orchestration_stage"]),
            query=(
                QuerySpec.model_validate(state["query_spec"]) if state.get("query_spec") else None
            ),
            plan=(AnalysisPlan.model_validate(state["plan"]) if state.get("plan") else None),
            planner_source=state.get("planner_source"),
            tool_results=[
                ToolResult.model_validate(item) for item in state.get("tool_results", [])
            ],
            evidence=[Evidence.model_validate(item) for item in state.get("evidence", [])],
            timings=[
                StageTiming.model_validate(item) for item in state.get("orchestration_timings", [])
            ],
            errors=state.get("errors", []),
            selected_skills=(skill_selection.selected_ids if skill_selection else []),
            skill_selection_reason=(skill_selection.reason if skill_selection else None),
            policy_version=state.get("policy_version"),
            budget=state.get("budget_snapshot"),
            completion=state.get("completion"),
            memory_scope=MemoryScope(
                tenant_id=state.get("tenant_id", "local"),
                user_id=state.get("user_id", "local"),
                session_id=state.get("session_id", "default"),
            ),
            memory_warnings=state.get("memory_warnings", []),
            context_manifests=state.get("context_manifests", {}),
            semantic_alignment=(
                SemanticAlignmentResult.model_validate(
                    state["semantic_alignment"]
                )
                if state.get("semantic_alignment")
                else None
            ),
            execution_metadata=(
                ExecutionMetadata.model_validate(state["execution_metadata"])
                if state.get("execution_metadata")
                and (state["execution_metadata"] or {}).get(
                    "business_reference_date"
                )
                else None
            ),
        )
        reporting = None
        status = state.get("reporting_status")
        if status and status != "revision_required":
            reporting = ReportingResult(
                status=status,
                report=(
                    ResearchReport.model_validate(state["final_report"])
                    if state.get("final_report")
                    else None
                ),
                validation=(
                    ValidationResult.model_validate(state["validation"])
                    if state.get("validation")
                    else None
                ),
                attempts=state.get("report_attempts", 0),
                timings=state.get("reporting_timings", {}),
                errors=state.get("reporting_errors", []),
            )
        return ResearchRunResult(
            success=bool(reporting and reporting.status == "completed"),
            orchestration=orchestration,
            reporting=reporting,
        )

    @staticmethod
    def _terminal_failure(run_id: str, error: str) -> ResearchRunResult:
        return ResearchRunResult(
            success=False,
            orchestration=OrchestrationResult(
                run_id=run_id,
                success=False,
                stage=RunStage.FAILED,
                query=None,
                plan=None,
                planner_source=None,
                tool_results=[],
                evidence=[],
                timings=[],
                errors=[error],
            ),
        )
