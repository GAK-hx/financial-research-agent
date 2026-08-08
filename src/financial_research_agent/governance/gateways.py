from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import ToolMessage, message_to_dict

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import (
    AnalysisPlan,
    AnalysisTask,
    QuerySpec,
    ToolResult,
)
from financial_research_agent.governance.models import (
    ModelGatewayResponse,
)
from financial_research_agent.governance.policy import PolicyEngine
from financial_research_agent.governance.store import GovernanceStore
from financial_research_agent.orchestration.registry import ToolRegistry
from financial_research_agent.persistence.store import (
    BusinessStore,
    OperationInProgress,
    canonical_hash,
)
from financial_research_agent.providers.model import OpenAICompatibleProvider
from financial_research_agent.skills.models import SkillSelection


def _safe_failure_code(exc: Exception) -> str:
    """Return an auditable error code without persisting provider/tool secrets."""
    return f"{type(exc).__name__}:execution_failed"


@dataclass
class _ModelAttemptObserver:
    run_id: str
    node_name: str
    operation: str
    policy: PolicyEngine
    governance: GovernanceStore
    count: int = 0

    async def before_attempt(self, attempt: int):
        await self.policy.authorize_model(
            run_id=self.run_id,
            node_name=self.node_name,
            operation=self.operation,
        )
        reservation = await self.governance.reserve(
            run_id=self.run_id,
            reservation_key=(f"{self.run_id}:{self.node_name}:model_attempt:{attempt + 1}"),
            resource="model_attempts",
            metadata={"node": self.node_name, "attempt": attempt + 1},
        )
        self.count = max(self.count, attempt + 1)
        return reservation

    async def after_attempt(self, token, *, succeeded: bool) -> None:
        # An actual outbound request consumes the retry-attempt budget even when
        # the provider or network returns an error.
        await self.governance.commit(token.entry_id)


class ModelGateway:
    def __init__(
        self,
        settings: Settings,
        provider: OpenAICompatibleProvider,
        business: BusinessStore,
        governance: GovernanceStore,
        policy: PolicyEngine,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.business = business
        self.governance = governance
        self.policy = policy

    async def create_plan(
        self,
        *,
        run_id: str,
        question: str,
        query: QuerySpec,
        tool_schemas: list[dict],
        planning_context: dict[str, Any] | None = None,
        context_manifest_id: str | None = None,
    ) -> dict:
        return (
            await self._invoke(
                run_id=run_id,
                node_name="plan",
                operation="plan",
                request_payload={
                    "question": question,
                    "query": query.model_dump(mode="json"),
                    "tool_names": [item["name"] for item in tool_schemas],
                    "prompt_version": self.settings.planner_prompt_version,
                    "context_manifest_id": context_manifest_id,
                },
                invoke=lambda observer: self.provider.create_plan_response(
                    question,
                    query,
                    tool_schemas,
                    attempt_observer=observer,
                    planning_context=planning_context,
                ),
            )
        ).content

    async def create_report(
        self,
        *,
        run_id: str,
        node_name: str,
        question: str,
        report_context: dict,
        draft: dict | None = None,
        validation_errors: list[str] | None = None,
        context_manifest_id: str | None = None,
    ) -> dict:
        operation = "revise_report" if node_name == "revise_report" else "generate_report"
        return (
            await self._invoke(
                run_id=run_id,
                node_name=node_name,
                operation=operation,
                request_payload={
                    "question": question,
                    "query": report_context.get("query"),
                    "evidence_ids": [
                        item.get("evidence_id") for item in report_context.get("evidence", [])
                    ],
                    "has_draft": draft is not None,
                    "validation_error_count": len(validation_errors or []),
                    "prompt_version": self.settings.report_prompt_version,
                    "context_manifest_id": context_manifest_id,
                },
                invoke=lambda observer: self.provider.create_report_response(
                    question,
                    report_context,
                    draft=draft,
                    validation_errors=validation_errors,
                    attempt_observer=observer,
                ),
            )
        ).content

    async def create_context_summary(
        self,
        *,
        run_id: str,
        target_node: str,
        context: dict[str, Any],
    ) -> dict:
        return (
            await self._invoke(
                run_id=run_id,
                node_name=f"context_summary_{target_node}",
                operation="summarize_context",
                request_payload={
                    "target_node": target_node,
                    "context_hash": canonical_hash(context),
                    "prompt_version": (self.settings.context_summary_prompt_version),
                },
                invoke=lambda observer: self.provider.create_context_summary_response(
                    context, attempt_observer=observer
                ),
            )
        ).content

    async def _invoke(
        self,
        *,
        run_id: str,
        node_name: str,
        operation: str,
        request_payload: dict[str, Any],
        invoke,
    ) -> ModelGatewayResponse:
        decision = await self.policy.authorize_model(
            run_id=run_id,
            node_name=node_name,
            operation=operation,
        )
        logical_budget = await self.governance.reserve(
            run_id=run_id,
            reservation_key=f"{run_id}:{node_name}:model_call",
            resource="model_calls",
            metadata={"node": node_name, "operation": operation},
        )
        call = await self.business.reserve_model_call(
            run_id=run_id,
            node_name=node_name,
            idempotency_key=f"{run_id}:{node_name}:model",
            provider=self.settings.model_provider,
            model_name=self.settings.model_name,
            request_payload=request_payload,
            gateway_version=self.settings.gateway_version,
            policy_decision_id=decision.decision_id,
            budget_entry_id=logical_budget.entry_id,
        )
        if not call.execute:
            if logical_budget.status == "reserved":
                await self.governance.commit(logical_budget.entry_id)
            return ModelGatewayResponse.model_validate(call.result_payload)
        observer = _ModelAttemptObserver(
            run_id=run_id,
            node_name=node_name,
            operation=operation,
            policy=self.policy,
            governance=self.governance,
        )
        try:
            response = await invoke(observer)
            await self._record_usage(
                run_id=run_id,
                node_name=node_name,
                call_id=call.call_id,
                response=response,
                attempt_count=observer.count,
            )
            await self.business.complete_model_call(call.call_id, response.model_dump(mode="json"))
            await self.governance.commit(logical_budget.entry_id)
            return response
        except Exception as exc:
            await self.business.record_model_attempts(call.call_id, attempt_count=observer.count)
            await self.business.fail_model_call(call.call_id, _safe_failure_code(exc))
            await self.governance.release(logical_budget.entry_id)
            raise

    async def _record_usage(
        self,
        *,
        run_id: str,
        node_name: str,
        call_id: str,
        response: ModelGatewayResponse,
        attempt_count: int,
    ) -> None:
        usage = response.usage
        await self.business.record_model_usage(
            call_id,
            attempt_count=attempt_count,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            usage_estimated=usage.estimated,
            cost_microunits=usage.cost_microunits,
        )
        if usage.total_tokens:
            token_budget = await self.governance.reserve(
                run_id=run_id,
                reservation_key=f"{run_id}:{node_name}:tokens",
                resource="tokens",
                amount=usage.total_tokens,
                metadata={"node": node_name, "estimated": usage.estimated},
            )
            await self.governance.commit(token_budget.entry_id)
        if usage.cost_microunits:
            cost_budget = await self.governance.reserve(
                run_id=run_id,
                reservation_key=f"{run_id}:{node_name}:cost",
                resource="cost_microunits",
                amount=usage.cost_microunits,
                metadata={"node": node_name, "currency": "CNY"},
            )
            await self.governance.commit(cost_budget.entry_id)


class ToolGateway:
    def __init__(
        self,
        settings: Settings,
        registry: ToolRegistry,
        business: BusinessStore,
        governance: GovernanceStore,
        policy: PolicyEngine,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.business = business
        self.governance = governance
        self.policy = policy

    async def execute(
        self,
        *,
        run_id: str,
        plan: AnalysisPlan,
        selection: SkillSelection,
    ) -> list[ToolResult]:
        results, _ = await self.execute_with_messages(
            run_id=run_id,
            plan=plan,
            selection=selection,
        )
        return results

    async def execute_with_messages(
        self,
        *,
        run_id: str,
        plan: AnalysisPlan,
        selection: SkillSelection,
    ) -> tuple[list[ToolResult], list[dict[str, Any]]]:
        pending = {task.task_id: task for task in plan.tasks}
        completed: dict[str, ToolResult] = {}
        messages: dict[str, dict[str, Any]] = {}
        max_parallel = min(
            self.settings.max_parallel_tools,
            selection.workflow_constraints.max_parallel_tools,
        )
        semaphore = asyncio.Semaphore(max_parallel)
        while pending:
            ready = [task for task in pending.values() if set(task.depends_on).issubset(completed)]
            if not ready:
                raise ValueError("plan contains a dependency cycle")
            runnable: list[AnalysisTask] = []
            skipped: dict[str, ToolResult] = {}
            for task in ready:
                failed = [item for item in task.depends_on if not completed[item].success]
                if failed:
                    skipped_result = ToolResult(
                        task_id=task.task_id,
                        success=False,
                        error_code="DEPENDENCY_FAILED",
                        error_message=f"failed dependencies: {','.join(failed)}",
                        latency_ms=0,
                    )
                    skipped[task.task_id] = skipped_result
                    if self.settings.agent_framework == "langchain":
                        messages[task.task_id] = message_to_dict(
                            ToolMessage(
                                content=(f"{task.task_id} skipped because dependencies failed"),
                                tool_call_id=(f"{run_id}:execute_tools:{task.task_id}"),
                                name=task.tool_name.value,
                                artifact={"tool_result": skipped_result.model_dump(mode="json")},
                                status="error",
                            )
                        )
                else:
                    runnable.append(task)
            try:
                if self.settings.agent_framework == "langchain":
                    structured = await asyncio.gather(
                        *(
                            self._run_structured_task(
                                run_id,
                                task,
                                plan.query,
                                selection,
                                semaphore,
                            )
                            for task in runnable
                        )
                    )
                    executed = [item[0] for item in structured]
                    for task, (_, message) in zip(runnable, structured, strict=True):
                        messages[task.task_id] = message
                else:
                    executed = await asyncio.gather(
                        *(
                            self._run_task(
                                run_id,
                                task,
                                plan.query,
                                selection,
                                semaphore,
                            )
                            for task in runnable
                        )
                    )
            except OperationInProgress as exc:
                raise RuntimeError(str(exc)) from exc
            by_id = {task.task_id: result for task, result in zip(runnable, executed, strict=True)}
            by_id.update(skipped)
            for task in ready:
                completed[task.task_id] = by_id[task.task_id]
                pending.pop(task.task_id)
        return (
            [completed[task.task_id] for task in plan.tasks],
            [messages[task.task_id] for task in plan.tasks if task.task_id in messages],
        )

    async def _run_structured_task(
        self,
        run_id: str,
        task: AnalysisTask,
        query: QuerySpec,
        selection: SkillSelection,
        semaphore: asyncio.Semaphore,
    ) -> tuple[ToolResult, dict[str, Any]]:
        from financial_research_agent.integrations.langchain.tools import (
            build_governed_structured_tool,
        )

        tool = self.registry.get(task.tool_name.value)

        async def governed(arguments: dict[str, Any]) -> ToolResult:
            normalized = task.model_copy(update={"arguments": arguments})
            return await self._run_task(
                run_id,
                normalized,
                query,
                selection,
                semaphore,
            )

        structured_tool = build_governed_structured_tool(tool, governed)
        message = await structured_tool.ainvoke(
            {
                "type": "tool_call",
                "id": f"{run_id}:execute_tools:{task.task_id}",
                "name": task.tool_name.value,
                "args": task.arguments,
            }
        )
        if not isinstance(message, ToolMessage):
            raise TypeError("structured tool did not return ToolMessage")
        artifact = message.artifact or {}
        result = ToolResult.model_validate(artifact.get("tool_result"))
        message.status = "success" if result.success else "error"
        return result, message_to_dict(message)

    async def _run_task(
        self,
        run_id: str,
        task: AnalysisTask,
        query: QuerySpec,
        selection: SkillSelection,
        semaphore: asyncio.Semaphore,
    ) -> ToolResult:
        tool = self.registry.get(task.tool_name.value)
        decision, validated = await self.policy.authorize_tool(
            run_id=run_id,
            node_name="execute_tools",
            tool=tool,
            arguments=task.arguments,
            query=query,
            selection=selection,
        )
        logical_budget = await self.governance.reserve(
            run_id=run_id,
            reservation_key=f"{run_id}:execute_tools:{task.task_id}:logical",
            resource="tool_calls",
            metadata={"task_id": task.task_id, "tool": task.tool_name.value},
        )
        call = await self.business.reserve_tool_call(
            run_id=run_id,
            node_name="execute_tools",
            task_id=task.task_id,
            tool_name=task.tool_name.value,
            idempotency_key=f"{run_id}:execute_tools:{task.task_id}",
            input_payload=task.arguments,
            gateway_version=self.settings.gateway_version,
            policy_decision_id=decision.decision_id,
            budget_entry_id=logical_budget.entry_id,
        )
        if not call.execute:
            if logical_budget.status == "reserved":
                cached = ToolResult.model_validate(call.result_payload)
                if cached.success:
                    await self.governance.commit(logical_budget.entry_id)
                else:
                    await self.governance.release(logical_budget.entry_id)
            return ToolResult.model_validate(call.result_payload)
        started = time.perf_counter()
        attempts = 0
        try:
            result: ToolResult | None = None
            for attempt in range(self.settings.max_tool_retries + 1):
                attempts = attempt + 1
                await self.policy.authorize_tool(
                    run_id=run_id,
                    node_name="execute_tools",
                    tool=tool,
                    arguments=task.arguments,
                    query=query,
                    selection=selection,
                )
                attempt_budget = await self.governance.reserve(
                    run_id=run_id,
                    reservation_key=(f"{run_id}:execute_tools:{task.task_id}:attempt:{attempts}"),
                    resource="tool_attempts",
                    metadata={
                        "task_id": task.task_id,
                        "tool": task.tool_name.value,
                        "attempt": attempts,
                    },
                )
                try:
                    async with semaphore:
                        async with asyncio.timeout(tool.definition.timeout_seconds):
                            result = await tool.execute(task.task_id, validated)
                except TimeoutError:
                    result = ToolResult(
                        task_id=task.task_id,
                        success=False,
                        error_code="TOOL_TIMEOUT",
                        error_message=f"{tool.definition.name} timed out",
                        latency_ms=int((time.perf_counter() - started) * 1000),
                    )
                except Exception as exc:
                    result = ToolResult(
                        task_id=task.task_id,
                        success=False,
                        error_code="TOOL_EXECUTION_ERROR",
                        error_message=(f"{tool.definition.name} failed: {type(exc).__name__}"),
                        latency_ms=int((time.perf_counter() - started) * 1000),
                    )
                finally:
                    await self.governance.commit(attempt_budget.entry_id)
                transient = result.error_code in {
                    "SOURCE_UNAVAILABLE",
                    "REPORT_SEARCH_UNAVAILABLE",
                    "TOOL_TIMEOUT",
                }
                if result.success or not transient or attempt >= self.settings.max_tool_retries:
                    break
            if result is None:
                raise RuntimeError("tool gateway produced no result")
            await self.business.record_tool_attempts(call.call_id, attempt_count=attempts)
            await self.business.complete_tool_call(call.call_id, result.model_dump(mode="json"))
            if result.success:
                await self.governance.commit(logical_budget.entry_id)
            else:
                await self.governance.release(logical_budget.entry_id)
            return result
        except Exception as exc:
            await self.business.record_tool_attempts(call.call_id, attempt_count=attempts)
            await self.business.fail_tool_call(call.call_id, _safe_failure_code(exc))
            await self.governance.release(logical_budget.entry_id)
            raise
