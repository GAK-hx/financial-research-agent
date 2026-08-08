from datetime import date
import unittest

import pandas as pd

from financial_research_agent.analysis.engine import (
    calculate_fundamental_snapshot,
    calculate_market_factors,
    calculate_technical_snapshot,
)
from financial_research_agent.analysis.models import EvidenceSufficiency
from financial_research_agent.analysis.registry import FactorRegistry, UniverseRegistry
from financial_research_agent.analysis.sufficiency import EvidenceSufficiencyChecker
from financial_research_agent.domain.models import (
    AnalysisPlan,
    AnalysisTask,
    Intent,
    QuerySpec,
    ToolName,
)
from financial_research_agent.orchestration.interpreter import QueryInterpreter
from financial_research_agent.skills.registry import SkillRegistry


def _market_frame(rows: int = 80) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "stock_code": ["600519"] * rows,
            "trade_date": pd.bdate_range("2026-01-01", periods=rows).date,
            "close": [100 + index for index in range(rows)],
            "volume": [1_000_000 + index * 1000 for index in range(rows)],
            "amount": [100_000_000 + index * 10_000 for index in range(rows)],
        }
    )


def test_factor_registry_and_demo_universe_are_versioned() -> None:
    factors = FactorRegistry.builtin()
    universe = UniverseRegistry.builtin().get("demo_liquid_a_share")
    assert factors.version == "factor_registry_v1"
    assert len(factors.all()) == 12
    assert len(universe.members) == 20
    assert {"600519", "300750"}.issubset(universe.members)


def test_deterministic_market_and_fundamental_engines() -> None:
    frame = _market_frame()
    factors = calculate_market_factors(frame)
    snapshot = calculate_technical_snapshot("600519", frame)
    assert factors["momentum_20d"] == snapshot.momentum_20d
    assert snapshot.momentum_60d is not None
    assert snapshot.volatility_20d is not None
    assert snapshot.formula_version == "technical_analysis_v1"

    financial = pd.DataFrame(
        [
            {
                "stock_code": "600519",
                "report_date": date(2026, 3, 31),
                "announcement_date": date(2026, 4, 28),
                "revenue_yoy": 0.1,
                "parent_net_profit_yoy": 0.12,
                "roe_period": 0.08,
                "operating_cash_flow": 120.0,
                "parent_net_profit": 100.0,
                "debt_ratio": 0.25,
            }
        ]
    )
    fundamental = calculate_fundamental_snapshot("600519", financial)
    assert fundamental.operating_cashflow_to_profit == 1.2
    assert fundamental.point_in_time_eligible is False
    assert fundamental.data_limitations


def test_new_intents_select_versioned_skill_and_report_profile() -> None:
    interpreter = QueryInterpreter(today=date(2026, 8, 8))
    technical = interpreter.interpret("简版分析贵州茅台最近一年技术面和动量")
    assert technical.intent == Intent.TECHNICAL
    registry = SkillRegistry.from_builtin_catalog()
    selection = registry.select(
        technical,
        {"technical_analysis", "market_query", "indicator_calculator"},
    )
    assert selection.selected_ids == ["single_stock_technical@1.0.0"]
    assert selection.report_profiles[0].id == "concise"

    factor = interpreter.interpret("比较600519和300750的动量因子排名")
    assert factor.intent == Intent.FACTOR
    assert "factor" in factor.analysis_domains

    event = interpreter.interpret("分析贵州茅台最近一年的事件影响，重点关注渠道改革")
    assert event.intent == Intent.EVENT
    assert event.analysis_domains == ["event"]

    comprehensive = interpreter.interpret(
        "结合技术面、基本面和事件分析贵州茅台最近一年"
    )
    assert comprehensive.intent == Intent.COMPREHENSIVE
    assert comprehensive.analysis_domains == ["market", "financial", "event"]


def test_event_gap_can_trigger_only_one_bounded_supplement() -> None:
    query = QuerySpec(
        stock_codes=["600519"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 8, 8),
        intent=Intent.EVENT,
        dimensions=["event"],
        analysis_domains=["event"],
    )
    plan = AnalysisPlan(
        query=query,
        tasks=[
            AnalysisTask(
                task_id="event",
                tool_name=ToolName.EVENT_SEARCH,
                arguments={
                    "stock_code": "600519",
                    "start_date": date(2026, 1, 1),
                    "end_date": date(2026, 8, 8),
                    "query": "渠道改革",
                    "max_events": 8,
                },
            )
        ],
    )
    selection = SkillRegistry.from_builtin_catalog().select(query, {"event_search"})
    checker = EvidenceSufficiencyChecker()
    first = checker.check(
        selection=selection,
        evidence=[],
        original_plan=plan,
        replan_count=0,
    )
    assert isinstance(first, EvidenceSufficiency)
    assert first.replan_allowed is True
    assert first.missing[0].safe_arguments["query"] is None
    second = checker.check(
        selection=selection,
        evidence=[],
        original_plan=plan,
        replan_count=1,
    )
    assert second.replan_allowed is False
    assert second.termination_reason == "EVIDENCE_INSUFFICIENT_REPLAN_LIMIT"


class Step3AnalysisSkillsTests(unittest.TestCase):
    """Keep the Step 3 coverage in the project's unittest regression gate."""

    def test_factor_registry_and_demo_universe_are_versioned(self) -> None:
        test_factor_registry_and_demo_universe_are_versioned()

    def test_deterministic_market_and_fundamental_engines(self) -> None:
        test_deterministic_market_and_fundamental_engines()

    def test_new_intents_select_versioned_skill_and_report_profile(self) -> None:
        test_new_intents_select_versioned_skill_and_report_profile()

    def test_event_gap_can_trigger_only_one_bounded_supplement(self) -> None:
        test_event_gap_can_trigger_only_one_bounded_supplement()
