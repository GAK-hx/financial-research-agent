from financial_research_agent.config import Settings
from financial_research_agent.providers.model import build_model_provider
from financial_research_agent.reporting.reporter import EvidenceOnlyReporter
from financial_research_agent.reporting.service import ReportingService


def build_reporting_service(settings: Settings) -> ReportingService:
    if settings.model_provider != "openai_compatible":
        raise ValueError(f"unsupported model provider: {settings.model_provider}")
    provider = build_model_provider(settings)
    return ReportingService(settings, EvidenceOnlyReporter(settings, provider))
