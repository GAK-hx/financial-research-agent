from __future__ import annotations

from typing import Protocol

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import Evidence, QuerySpec, ResearchReport
from financial_research_agent.reporting.context import build_report_context
from financial_research_agent.reporting.facts import ReportFactExtractor


class ReportProvider(Protocol):
    async def create_report(
        self,
        question: str,
        report_context: dict,
        draft: dict | None = None,
        validation_errors: list[str] | None = None,
    ) -> dict: ...


class EvidenceOnlyReporter:
    def __init__(self, settings: Settings, provider: ReportProvider) -> None:
        self.settings = settings
        self.provider = provider

    async def generate(
        self,
        question: str,
        query: QuerySpec,
        evidence: list[Evidence],
        draft: ResearchReport | None = None,
        validation_errors: list[str] | None = None,
    ) -> ResearchReport:
        if not evidence:
            raise ValueError("formal report requires evidence")
        topics = query.report_request.deep_topics if query.report_request else []
        facts = ReportFactExtractor().extract(evidence, topics=topics)
        context = build_report_context(
            query,
            evidence,
            self.settings.max_report_context_chars,
            report_facts=facts,
        )
        raw = await self.provider.create_report(
            question,
            context,
            draft=draft.model_dump(mode="json") if draft else None,
            validation_errors=validation_errors,
        )
        return ResearchReport.model_validate(raw)
