from __future__ import annotations

import asyncio

from financial_research_agent.domain.models import AnalysisPlan, AnalysisTask, ToolResult
from financial_research_agent.orchestration.executor import PlanExecutor
from financial_research_agent.persistence.store import BusinessStore, OperationInProgress


class PersistentPlanExecutor:
    """Dependency-aware tool execution with completed-result reuse by task."""

    def __init__(self, base: PlanExecutor, store: BusinessStore) -> None:
        self.base = base
        self.store = store

    async def _run_task(self, run_id: str, task: AnalysisTask) -> ToolResult:
        key = f"{run_id}:execute_tools:{task.task_id}"
        reservation = await self.store.reserve_tool_call(
            run_id=run_id,
            node_name="execute_tools",
            task_id=task.task_id,
            tool_name=task.tool_name.value,
            idempotency_key=key,
            input_payload=task.arguments,
        )
        if not reservation.execute:
            return ToolResult.model_validate(reservation.result_payload)
        try:
            result = await self.base._run_task(task)
            await self.store.complete_tool_call(
                reservation.call_id, result.model_dump(mode="json")
            )
            return result
        except Exception as exc:
            await self.store.fail_tool_call(
                reservation.call_id, f"{type(exc).__name__}:{exc}"
            )
            raise

    async def execute(self, run_id: str, plan: AnalysisPlan) -> list[ToolResult]:
        pending = {task.task_id: task for task in plan.tasks}
        completed: dict[str, ToolResult] = {}
        while pending:
            ready = [
                task
                for task in pending.values()
                if set(task.depends_on).issubset(completed)
            ]
            if not ready:
                raise ValueError("plan contains a dependency cycle")
            runnable: list[AnalysisTask] = []
            skipped: dict[str, ToolResult] = {}
            for task in ready:
                failed_dependencies = [
                    dependency
                    for dependency in task.depends_on
                    if not completed[dependency].success
                ]
                if failed_dependencies:
                    skipped[task.task_id] = ToolResult(
                        task_id=task.task_id,
                        success=False,
                        error_code="DEPENDENCY_FAILED",
                        error_message=f"failed dependencies: {','.join(failed_dependencies)}",
                        latency_ms=0,
                    )
                else:
                    runnable.append(task)
            try:
                executed = await asyncio.gather(
                    *(self._run_task(run_id, task) for task in runnable)
                )
            except OperationInProgress as exc:
                raise RuntimeError(str(exc)) from exc
            by_id = {
                task.task_id: result
                for task, result in zip(runnable, executed, strict=True)
            }
            by_id.update(skipped)
            for task in ready:
                completed[task.task_id] = by_id[task.task_id]
                pending.pop(task.task_id)
        return [completed[task.task_id] for task in plan.tasks]
