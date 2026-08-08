from financial_research_agent.config import Settings
from financial_research_agent.orchestration.interpreter import QueryInterpreter
from financial_research_agent.orchestration.registry import ToolRegistry
from financial_research_agent.orchestration.service import OrchestrationService
from financial_research_agent.providers.model import build_model_provider
from financial_research_agent.tools.financial import FinancialQueryTool
from financial_research_agent.tools.analysis import (
    FactorScreenTool,
    FundamentalAnalysisTool,
    StockComparisonTool,
    TechnicalAnalysisTool,
)
from financial_research_agent.tools.market import IndicatorTool, MarketQueryTool
from financial_research_agent.tools.report_search import ReportSearchTool


def build_formal_registry(settings: Settings) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(MarketQueryTool(settings))
    registry.register(IndicatorTool(settings))
    registry.register(FinancialQueryTool(settings))
    registry.register(ReportSearchTool(settings))
    registry.register(TechnicalAnalysisTool(settings))
    registry.register(FundamentalAnalysisTool(settings))
    registry.register(FactorScreenTool(settings))
    registry.register(StockComparisonTool(settings))
    return registry


def build_orchestration_service(settings: Settings) -> OrchestrationService:
    if settings.model_provider != "openai_compatible":
        raise ValueError(f"unsupported model provider: {settings.model_provider}")
    return OrchestrationService(
        settings,
        build_formal_registry(settings),
        provider=build_model_provider(settings),
        interpreter=QueryInterpreter(
            today=settings.evaluation_reference_date,
            timezone_name=settings.business_timezone,
        ),
    )
