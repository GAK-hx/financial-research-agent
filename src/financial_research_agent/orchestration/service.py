from __future__ import annotations

import asyncio
import time

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import ExecutionMetadata
from financial_research_agent.orchestration.context import (
    OrchestrationResult,
    RunContext,
    RunStage,
    StageTiming,
)
from financial_research_agent.orchestration.executor import PlanExecutor
from financial_research_agent.orchestration.interpreter import QueryInterpreter
from financial_research_agent.orchestration.planner import RulePlanner, StructuredPlanner
from financial_research_agent.orchestration.registry import ToolRegistry
from financial_research_agent.orchestration.semantic import SemanticAlignmentValidator
from financial_research_agent.orchestration.validator import PlanValidator
from financial_research_agent.providers.model import ModelProvider
from financial_research_agent.reporting.validators import evidence_data_as_of


class OrchestrationService:
    def __init__(
        self,
        settings: Settings,
        registry: ToolRegistry,
        provider: ModelProvider | None = None,
        interpreter: QueryInterpreter | None = None,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.interpreter = interpreter or QueryInterpreter()
        self.semantic_validator = SemanticAlignmentValidator(self.interpreter)
        self.planner = StructuredPlanner(registry, RulePlanner(registry), provider)
        self.validator = PlanValidator(settings, registry)
        self.executor = PlanExecutor(
            registry,
            max_parallel=settings.max_parallel_tools,
            max_retries=settings.max_tool_retries,
        )

    async def run(self, question: str) -> OrchestrationResult:
        context = RunContext(question=question)
        try:
            async with asyncio.timeout(self.settings.run_timeout_seconds):
                context.stage = RunStage.INTERPRETING
                started = time.perf_counter()
                context.query = self.interpreter.interpret(question)
                self._timing(context, RunStage.INTERPRETING, started)

                context.stage = RunStage.ALIGNING_SEMANTICS
                started = time.perf_counter()
                context.semantic_alignment = self.semantic_validator.validate(
                    question, context.query
                )
                self._timing(context, RunStage.ALIGNING_SEMANTICS, started)
                if not context.semantic_alignment.passed:
                    raise ValueError(
                        "SEMANTIC_ALIGNMENT_FAILED:"
                        + ",".join(context.semantic_alignment.errors)
                    )

                context.stage = RunStage.PLANNING
                started = time.perf_counter()
                context.plan, context.planner_source = await self.planner.create_plan(
                    question, context.query
                )
                self._timing(context, RunStage.PLANNING, started)

                context.stage = RunStage.VALIDATING_PLAN
                started = time.perf_counter()
                self.validator.validate(context.plan, expected_query=context.query)
                self._timing(context, RunStage.VALIDATING_PLAN, started)

                context.stage = RunStage.EXECUTING
                started = time.perf_counter()
                context.tool_results = await self.executor.execute(context.plan)
                self._timing(context, RunStage.EXECUTING, started)

                context.stage = RunStage.BUILDING_EVIDENCE
                started = time.perf_counter()
                context.collect_evidence(self.settings.max_evidence)
                self._timing(context, RunStage.BUILDING_EVIDENCE, started)
                context.errors.extend(
                    f"{result.task_id}:{result.error_code}:{result.error_message}"
                    for result in context.tool_results
                    if not result.success
                )
                context.stage = RunStage.COMPLETED if context.evidence_memory else RunStage.FAILED
        except TimeoutError:
            context.stage = RunStage.FAILED
            context.errors.append("RUN_TIMEOUT")
        except Exception as exc:
            context.stage = RunStage.FAILED
            context.errors.append(f"{type(exc).__name__}:{exc}")
        return OrchestrationResult(
            run_id=context.run_id,
            success=context.stage == RunStage.COMPLETED,
            stage=context.stage,
            query=context.query,
            plan=context.plan,
            planner_source=context.planner_source,
            tool_results=context.tool_results,
            evidence=context.evidence_memory,
            timings=context.timings,
            errors=context.errors,
            semantic_alignment=context.semantic_alignment,
            execution_metadata=ExecutionMetadata(
                executed_at=context.created_at,
                business_reference_date=self.interpreter.today,
                timezone=self.interpreter.timezone_name,
                data_as_of=evidence_data_as_of(context.evidence_memory),
            ),
        )

    @staticmethod
    def _timing(context: RunContext, stage: RunStage, started: float) -> None:
        context.timings.append(
            StageTiming(stage=stage, duration_ms=int((time.perf_counter() - started) * 1000))
        )
