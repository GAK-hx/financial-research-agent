from __future__ import annotations

from typing import Protocol

from financial_research_agent.config import Settings
from financial_research_agent.research import ResearchRunResult, ResearchService


class ResearchRuntime(Protocol):
    async def analyze(
        self,
        question: str,
        *,
        tenant_id: str = "local",
        user_id: str = "local",
        session_id: str = "default",
    ) -> ResearchRunResult: ...


def build_research_service(settings: Settings) -> ResearchRuntime:
    """Select the research runtime without importing LangGraph for legacy deployments."""
    if settings.orchestration_runtime == "legacy":
        return ResearchService(settings)
    if settings.orchestration_runtime == "langgraph":
        from financial_research_agent.orchestration.langgraph_runtime import (
            LangGraphResearchService,
        )

        return LangGraphResearchService(settings)
    raise ValueError(f"unsupported orchestration runtime: {settings.orchestration_runtime}")
