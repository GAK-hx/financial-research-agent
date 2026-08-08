from __future__ import annotations

import asyncio
import time

from pydantic import BaseModel

from financial_research_agent.config import Settings
from financial_research_agent.orchestration.context import OrchestrationResult
from financial_research_agent.orchestration.factory import build_orchestration_service
from financial_research_agent.reporting.factory import build_reporting_service
from financial_research_agent.reporting.service import ReportingResult


class ResearchRunResult(BaseModel):
    success: bool
    orchestration: OrchestrationResult
    reporting: ReportingResult | None = None


class ResearchService:
    def __init__(self, settings: Settings, orchestration=None, reporting=None) -> None:
        self.settings = settings
        self.orchestration = orchestration or build_orchestration_service(settings)
        self.reporting = reporting or build_reporting_service(settings)

    async def analyze(
        self,
        question: str,
        *,
        tenant_id: str = "local",
        user_id: str = "local",
        session_id: str = "default",
    ) -> ResearchRunResult:
        started = time.perf_counter()
        orchestration = await self.orchestration.run(question)
        if not orchestration.success or orchestration.query is None:
            return ResearchRunResult(success=False, orchestration=orchestration)
        elapsed = time.perf_counter() - started
        remaining = max(0.001, self.settings.run_timeout_seconds - elapsed)
        try:
            async with asyncio.timeout(remaining):
                reporting = await self.reporting.run(
                    question,
                    orchestration.query,
                    orchestration.evidence,
                    orchestration.run_id,
                )
        except TimeoutError:
            reporting = ReportingResult(
                status="generation_failed",
                attempts=1,
                timings={"total_timeout_ms": int((time.perf_counter() - started) * 1000)},
                errors=["RUN_TIMEOUT"],
            )
        return ResearchRunResult(
            success=reporting.status == "completed",
            orchestration=orchestration,
            reporting=reporting,
        )
