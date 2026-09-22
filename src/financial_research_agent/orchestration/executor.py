from __future__ import annotations

import asyncio
import time

from financial_research_agent.domain.models import AnalysisPlan, AnalysisTask, ToolResult
from financial_research_agent.orchestration.registry import ToolRegistry


class PlanExecutor:
    def __init__(
        self, registry: ToolRegistry, max_parallel: int = 4, max_retries: int = 2
    ) -> None:
        self.registry = registry
        self.semaphore = asyncio.Semaphore(max_parallel)
        self.max_retries = max_retries

    async def _run_task(self, task: AnalysisTask) -> ToolResult:
        tool = self.registry.get(task.tool_name.value)
        validated = tool.validate_input(task.arguments)
        started = time.perf_counter()
        for attempt in range(self.max_retries + 1):
            try:
                async with self.semaphore:
                    async with asyncio.timeout(tool.definition.timeout_seconds):
                        result = await tool.execute(task.task_id, validated)
                transient = result.error_code in {
                    "SOURCE_UNAVAILABLE",
                    "REPORT_SEARCH_UNAVAILABLE",
                    "REPORT_CONTENT_UNAVAILABLE",
                }
                if result.success or not transient or attempt == self.max_retries:
                    return result
            except TimeoutError:
                if attempt == self.max_retries:
                    return ToolResult(
                        task_id=task.task_id,
                        success=False,
                        error_code="TOOL_TIMEOUT",
                        error_message=f"{tool.definition.name} timed out",
                        latency_ms=int((time.perf_counter() - started) * 1000),
                    )
            except Exception as exc:
                if attempt == self.max_retries:
                    return ToolResult(
                        task_id=task.task_id,
                        success=False,
                        error_code="TOOL_EXECUTION_ERROR",
                        error_message=str(exc),
                        latency_ms=int((time.perf_counter() - started) * 1000),
                    )
        raise RuntimeError("unreachable retry state")

    async def execute(self, plan: AnalysisPlan) -> list[ToolResult]:
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
                    dependency for dependency in task.depends_on if not completed[dependency].success
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
            executed = await asyncio.gather(*(self._run_task(task) for task in runnable))
            result_by_id = {task.task_id: result for task, result in zip(runnable, executed, strict=True)}
            result_by_id.update(skipped)
            for task in ready:
                completed[task.task_id] = result_by_id[task.task_id]
                pending.pop(task.task_id)

        return [completed[task.task_id] for task in plan.tasks]
