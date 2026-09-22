from __future__ import annotations

from financial_research_agent.domain.models import (
    AnalysisPlan,
    AnalysisTask,
    Intent,
    QuerySpec,
    ToolName,
)
from financial_research_agent.orchestration.registry import ToolRegistry
from financial_research_agent.providers.model import ModelProvider


class RulePlanner:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def create_plan(self, query: QuerySpec, question: str = "") -> AnalysisPlan:
        stock_code = query.stock_codes[0]
        tasks: list[AnalysisTask] = []
        domains = set(query.analysis_domains) or {
            Intent.MARKET: {"market"},
            Intent.TECHNICAL: {"market"},
            Intent.FINANCIAL: {"financial"},
            Intent.FUNDAMENTAL: {"financial"},
            Intent.REPORT: {"report"},
            Intent.EVENT: {"event"},
            Intent.SCREENING: {"market"},
            Intent.FACTOR: {"factor"},
            Intent.COMPREHENSIVE: {"market", "report"},
        }[query.intent]
        if query.intent == Intent.TECHNICAL:
            tasks.append(AnalysisTask(task_id="technical", tool_name=ToolName.TECHNICAL_ANALYSIS, arguments={"stock_code": stock_code}))
        elif query.intent == Intent.FUNDAMENTAL:
            tasks.append(AnalysisTask(task_id="fundamental", tool_name=ToolName.FUNDAMENTAL_ANALYSIS, arguments={"stock_code": stock_code}))
        elif query.intent == Intent.SCREENING:
            tasks.append(AnalysisTask(task_id="comparison", tool_name=ToolName.STOCK_COMPARISON, arguments={"stock_codes": query.stock_codes}))
        elif query.intent == Intent.FACTOR:
            tasks.append(AnalysisTask(task_id="factor", tool_name=ToolName.FACTOR_SCREEN, arguments={"stock_codes": query.stock_codes}))
        elif query.intent == Intent.EVENT:
            for code in query.stock_codes:
                tasks.append(AnalysisTask(task_id=f"web_{code}", tool_name=ToolName.WEB_SEARCH, arguments={"stock_code": code, "query": question[:300] or code}))
        elif query.intent == Intent.COMPREHENSIVE:
            if "market" in domains:
                if "technical_analysis" in query.dimensions:
                    tasks.append(AnalysisTask(task_id="technical", tool_name=ToolName.TECHNICAL_ANALYSIS, arguments={"stock_code": stock_code}))
                else:
                    self._append_legacy_tasks(tasks, query, question, {"market"}, stock_code)
            if "financial" in domains:
                if "fundamental_analysis" in query.dimensions:
                    tasks.append(AnalysisTask(task_id="fundamental", tool_name=ToolName.FUNDAMENTAL_ANALYSIS, arguments={"stock_code": stock_code}))
                else:
                    self._append_legacy_tasks(tasks, query, question, {"financial"}, stock_code)
            if "report" in domains:
                tasks.append(AnalysisTask(task_id="report_candidates", tool_name=ToolName.REPORT_CANDIDATE_SEARCH, arguments={"stock_code": stock_code, "query": question or stock_code}))
            if "event" in domains:
                for code in query.stock_codes:
                    tasks.append(AnalysisTask(task_id=f"web_{code}", tool_name=ToolName.WEB_SEARCH, arguments={"stock_code": code, "query": question[:300] or code}))
            if "factor" in domains:
                tasks.append(AnalysisTask(task_id="factor", tool_name=ToolName.FACTOR_SCREEN, arguments={"stock_codes": query.stock_codes}))
        else:
            self._append_legacy_tasks(tasks, query, question, domains, stock_code)
        for task in tasks:
            self.registry.get(task.tool_name.value)
        return AnalysisPlan(query=query, tasks=tasks, expected_sections=[query.intent.value])

    def _append_legacy_tasks(
        self,
        tasks: list[AnalysisTask],
        query: QuerySpec,
        question: str,
        domains: set[str],
        stock_code: str,
    ) -> None:
        if "market" in domains:
            market_arguments = {
                "stock_code": stock_code,
                "start_date": query.start_date,
                "end_date": query.end_date,
                "adjust_type": "qfq",
            }
            tasks.extend(
                [
                    AnalysisTask(
                        task_id="market",
                        tool_name=ToolName.MARKET_QUERY,
                        arguments=market_arguments,
                    ),
                    AnalysisTask(
                        task_id="indicator",
                        tool_name=ToolName.INDICATOR_CALCULATOR,
                        arguments=market_arguments,
                        depends_on=["market"],
                    ),
                ]
            )
        if "report" in domains:
            tasks.append(
                AnalysisTask(
                    task_id="report_candidates",
                    tool_name=ToolName.REPORT_CANDIDATE_SEARCH,
                    arguments={"stock_code": stock_code, "query": question or stock_code},
                )
            )
        if "financial" in domains:
            tasks.append(
                AnalysisTask(
                    task_id="financial",
                    tool_name=ToolName.FINANCIAL_QUERY,
                    arguments={
                        "stock_code": stock_code,
                        "start_date": query.start_date,
                        "end_date": query.end_date,
                    },
                )
            )


class StructuredPlanner:
    def __init__(
        self,
        registry: ToolRegistry,
        rule_planner: RulePlanner,
        provider: ModelProvider | None = None,
    ) -> None:
        self.registry = registry
        self.rule_planner = rule_planner
        self.provider = provider

    async def create_plan(self, question: str, query: QuerySpec) -> tuple[AnalysisPlan, str]:
        if self.provider is not None:
            try:
                raw_plan = await self.provider.create_plan(question, query, self.registry.schemas())
                return AnalysisPlan.model_validate(raw_plan), "model"
            except Exception:
                pass
        return self.rule_planner.create_plan(query, question), "rule_fallback"
