from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import (
    Evidence,
    QuerySpec,
    ResearchReport,
    ValidationResult,
)
from financial_research_agent.reporting.reporter import EvidenceOnlyReporter
from financial_research_agent.reporting.validators import (
    ReportValidator,
    bind_report_data_as_of,
    bind_report_scope,
)


class ReportingResult(BaseModel):
    status: Literal["completed", "generation_failed", "validation_failed"]
    report: ResearchReport | None = None
    validation: ValidationResult | None = None
    attempts: int = Field(ge=0, le=2)
    timings: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class ReportingService:
    def __init__(
        self,
        settings: Settings,
        reporter: EvidenceOnlyReporter,
        validator: ReportValidator | None = None,
    ) -> None:
        self.settings = settings
        self.reporter = reporter
        self.validator = validator or ReportValidator()

    async def run(
        self,
        question: str,
        query: QuerySpec,
        evidence: list[Evidence],
        run_id: str,
    ) -> ReportingResult:
        timings: dict[str, int] = {}
        started = time.perf_counter()
        try:
            report = await self.reporter.generate(question, query, evidence)
            report = bind_report_scope(report, query)
            report = bind_report_data_as_of(report, evidence)
        except Exception as exc:
            timings["generate_report"] = int((time.perf_counter() - started) * 1000)
            return ReportingResult(
                status="generation_failed",
                attempts=1,
                timings=timings,
                errors=[f"{type(exc).__name__}:{exc}"],
            )
        timings["generate_report"] = int((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        validation = self.validator.validate(report, query, evidence, run_id)
        timings["validate_report"] = int((time.perf_counter() - started) * 1000)
        if validation.passed:
            return ReportingResult(
                status="completed",
                report=report,
                validation=validation,
                attempts=1,
                timings=timings,
            )
        if self.settings.max_report_revisions == 0:
            return ReportingResult(
                status="validation_failed",
                report=report,
                validation=validation,
                attempts=1,
                timings=timings,
                errors=validation.errors,
            )
        started = time.perf_counter()
        try:
            revised = await self.reporter.generate(
                question,
                query,
                evidence,
                draft=report,
                validation_errors=validation.errors,
            )
            revised = bind_report_scope(revised, query)
            revised = bind_report_data_as_of(revised, evidence)
        except Exception as exc:
            timings["revise_report"] = int((time.perf_counter() - started) * 1000)
            return ReportingResult(
                status="generation_failed",
                report=report,
                validation=validation,
                attempts=2,
                timings=timings,
                errors=[*validation.errors, f"{type(exc).__name__}:{exc}"],
            )
        timings["revise_report"] = int((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        revised_validation = self.validator.validate(revised, query, evidence, run_id)
        timings["validate_revision"] = int((time.perf_counter() - started) * 1000)
        return ReportingResult(
            status="completed" if revised_validation.passed else "validation_failed",
            report=revised,
            validation=revised_validation,
            attempts=2,
            timings=timings,
            errors=[] if revised_validation.passed else revised_validation.errors,
        )
