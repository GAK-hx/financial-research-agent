from __future__ import annotations

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import AnalysisPlan, Intent, QuerySpec, ToolName
from financial_research_agent.orchestration.registry import ToolRegistry


class PlanValidator:
    def __init__(self, settings: Settings, registry: ToolRegistry) -> None:
        self.settings = settings
        self.registry = registry

    def validate(
        self, plan: AnalysisPlan, expected_query: QuerySpec | None = None
    ) -> AnalysisPlan:
        if expected_query is not None and plan.query != expected_query:
            raise ValueError("plan query differs from interpreted query")
        if not set(plan.query.stock_codes).issubset(self.settings.allowed_stock_codes):
            raise ValueError("plan contains a stock outside configured pool")
        if len(plan.tasks) > self.settings.max_plan_tasks:
            raise ValueError("plan exceeds task budget")
        if len(plan.tasks) > self.settings.max_tool_calls:
            raise ValueError("plan exceeds tool-call budget")
        known_ids = {task.task_id for task in plan.tasks}
        graph = {task.task_id: set(task.depends_on) for task in plan.tasks}
        for task in plan.tasks:
            tool = self.registry.get(task.tool_name.value)
            if not tool.definition.read_only:
                raise ValueError(f"tool is not read-only: {tool.definition.name}")
            if tool.definition.data_domain == "simulation":
                raise ValueError("simulation tools are forbidden in formal mode")
            validated_arguments = tool.validate_input(task.arguments)
            stock_code = getattr(validated_arguments, "stock_code", None)
            if stock_code and stock_code not in plan.query.stock_codes:
                raise ValueError("tool stock differs from plan query")
            stock_codes = getattr(validated_arguments, "stock_codes", None)
            if stock_codes and not set(stock_codes).issubset(plan.query.stock_codes):
                raise ValueError("tool stocks differ from plan query")
            if not graph[task.task_id].issubset(known_ids):
                raise ValueError("plan contains an unknown dependency")
        tasks_by_tool = {task.tool_name: task for task in plan.tasks}
        allowed_tools = self.allowed_tools_for_query(plan.query)
        unexpected_tools = set(tasks_by_tool) - allowed_tools
        if unexpected_tools:
            unexpected = ",".join(
                sorted(tool.value for tool in unexpected_tools)
            )
            raise ValueError(
                f"plan contains tools outside intent boundary: {unexpected}"
            )
        missing_tools = allowed_tools - set(tasks_by_tool)
        if missing_tools:
            missing = ",".join(sorted(tool.value for tool in missing_tools))
            raise ValueError(f"plan is missing required tools: {missing}")
        if plan.query.intent == Intent.SCREENING:
            comparison_tasks = [
                task
                for task in plan.tasks
                if task.tool_name == ToolName.STOCK_COMPARISON
            ]
            if len(plan.tasks) != 1 or len(comparison_tasks) != 1:
                raise ValueError(
                    "screening plan must contain exactly one stock comparison"
                )
        indicator = tasks_by_tool.get(ToolName.INDICATOR_CALCULATOR)
        market = tasks_by_tool.get(ToolName.MARKET_QUERY)
        if indicator is not None and market is not None and market.task_id not in indicator.depends_on:
            raise ValueError("indicator task must depend on market task")
        visited: set[str] = set()
        active: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in active:
                raise ValueError("plan contains a dependency cycle")
            if task_id in visited:
                return
            active.add(task_id)
            for dependency in graph[task_id]:
                visit(dependency)
            active.remove(task_id)
            visited.add(task_id)

        for task_id in graph:
            visit(task_id)
        return plan

    @staticmethod
    def allowed_tools_for_intent(intent: Intent) -> set[ToolName]:
        return {
            Intent.MARKET: {ToolName.MARKET_QUERY, ToolName.INDICATOR_CALCULATOR},
            Intent.TECHNICAL: {ToolName.TECHNICAL_ANALYSIS},
            Intent.FINANCIAL: {ToolName.FINANCIAL_QUERY},
            Intent.FUNDAMENTAL: {ToolName.FUNDAMENTAL_ANALYSIS},
            Intent.REPORT: {ToolName.REPORT_CANDIDATE_SEARCH},
            Intent.EVENT: {ToolName.WEB_SEARCH},
            Intent.SCREENING: {ToolName.STOCK_COMPARISON},
            Intent.FACTOR: {ToolName.FACTOR_SCREEN},
            Intent.COMPREHENSIVE: {
                ToolName.TECHNICAL_ANALYSIS,
                ToolName.REPORT_CANDIDATE_SEARCH,
            },
        }[intent]

    @classmethod
    def allowed_tools_for_query(cls, query: QuerySpec) -> set[ToolName]:
        if query.intent != Intent.COMPREHENSIVE:
            return cls.allowed_tools_for_intent(query.intent)
        tools: set[ToolName] = set()
        if "market" in query.analysis_domains:
            if "technical_analysis" in query.dimensions:
                tools.add(ToolName.TECHNICAL_ANALYSIS)
            else:
                tools.add(ToolName.MARKET_QUERY)
            if query.intent == Intent.MARKET:
                tools.add(ToolName.INDICATOR_CALCULATOR)
            elif query.intent == Intent.COMPREHENSIVE and "technical_analysis" not in query.dimensions:
                tools.add(ToolName.INDICATOR_CALCULATOR)
        if "financial" in query.analysis_domains:
            tools.add(
                ToolName.FUNDAMENTAL_ANALYSIS
                if "fundamental_analysis" in query.dimensions
                else ToolName.FINANCIAL_QUERY
            )
        if "report" in query.analysis_domains:
            tools.add(ToolName.REPORT_CANDIDATE_SEARCH)
        if "event" in query.analysis_domains:
            tools.add(ToolName.WEB_SEARCH)
        if "factor" in query.analysis_domains:
            tools.add(ToolName.FACTOR_SCREEN)
        return tools

    @staticmethod
    def normalize_for_execution(
        plan: AnalysisPlan, question: str
    ) -> AnalysisPlan:
        """Make data-access arguments reproducible without changing the DAG."""
        single_stock_code = (
            plan.query.stock_codes[0]
            if len(plan.query.stock_codes) == 1
            else None
        )
        normalized_tasks = []
        for task in plan.tasks:
            arguments = dict(task.arguments)
            if single_stock_code is not None and task.tool_name not in {
                ToolName.FACTOR_SCREEN,
                ToolName.STOCK_COMPARISON,
            }:
                arguments["stock_code"] = single_stock_code
            if task.tool_name in {
                ToolName.MARKET_QUERY,
                ToolName.INDICATOR_CALCULATOR,
                ToolName.FINANCIAL_QUERY,
                ToolName.TECHNICAL_ANALYSIS,
                ToolName.FUNDAMENTAL_ANALYSIS,
                ToolName.STOCK_COMPARISON,
                ToolName.EVENT_SEARCH,
                ToolName.WEB_SEARCH,
            }:
                arguments["start_date"] = plan.query.start_date
                arguments["end_date"] = plan.query.end_date
            if task.tool_name in {
                ToolName.MARKET_QUERY,
                ToolName.INDICATOR_CALCULATOR,
                ToolName.TECHNICAL_ANALYSIS,
            }:
                arguments["adjust_type"] = "qfq"
            if task.tool_name == ToolName.REPORT_CANDIDATE_SEARCH:
                arguments["query"] = question
                request = plan.query.report_request
                if request is None:
                    raise ValueError("report plan lacks report request")
                arguments.update(
                    {
                        "reference_date": request.end_date,
                        "top_k": request.candidate_top_k,
                        "minimum_candidates": request.minimum_candidates,
                        "explicit_date_range": request.explicit_date_range,
                        "start_date": request.start_date,
                        "end_date": request.end_date,
                        "institution": (
                            request.institution_filters[0]
                            if request.institution_filters
                            else None
                        ),
                        "title_keywords": request.title_keywords,
                        "allow_unknown_date": request.allow_unknown_date,
                    }
                )
            if task.tool_name == ToolName.EVENT_SEARCH:
                arguments["query"] = question[:200]
                arguments["max_events"] = 8
            if task.tool_name == ToolName.WEB_SEARCH:
                labels = ["公开公告", "新闻", "经营进展"]
                if "risk" in plan.query.dimensions:
                    labels.append("风险")
                if any(
                    item in plan.query.dimensions
                    for item in ("financial_growth", "profitability", "leverage")
                ):
                    labels.append("财务业绩")
                arguments["query"] = " ".join(labels)
                arguments["max_results"] = 8
                arguments["topic"] = "news"
            if task.tool_name == ToolName.FACTOR_SCREEN:
                arguments["stock_codes"] = plan.query.stock_codes
                arguments["as_of_date"] = plan.query.end_date
                arguments["universe_id"] = "demo_liquid_a_share"
                arguments["factor_names"] = PlanValidator.factor_names_for_query(
                    plan.query
                )
                arguments["top_n"] = min(10, len(plan.query.stock_codes))
            if task.tool_name == ToolName.STOCK_COMPARISON:
                arguments["stock_codes"] = plan.query.stock_codes
            normalized_tasks.append(
                task.model_copy(update={"arguments": arguments})
            )
        return plan.model_copy(update={"tasks": normalized_tasks})

    @staticmethod
    def factor_names_for_query(query: QuerySpec) -> list[str]:
        mapping = {
            "momentum": "momentum_20d",
            "volatility": "volatility_20d",
            "drawdown": "max_drawdown_60d",
            "volume": "relative_volume_20d",
            "liquidity": "amihud_liquidity_20d",
            "financial_growth": "revenue_growth",
            "profitability": "roe",
            "leverage": "debt_to_assets",
        }
        selected = [mapping[item] for item in query.dimensions if item in mapping]
        return list(dict.fromkeys(selected)) or [
            "momentum_20d", "volatility_20d", "revenue_growth", "roe"
        ]
