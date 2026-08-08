import unittest
from datetime import date

from pydantic import ValidationError

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import Intent, QuerySpec


class QuerySpecTests(unittest.TestCase):
    def test_accepts_valid_stock_and_dates(self) -> None:
        spec = QuerySpec(
            stock_codes=["600519"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            intent=Intent.MARKET,
        )
        self.assertEqual(spec.stock_codes, ["600519"])

    def test_rejects_invalid_stock_code(self) -> None:
        with self.assertRaises(ValidationError):
            QuerySpec(stock_codes=["贵州茅台"], intent=Intent.MARKET)

    def test_evaluation_reference_date_is_explicit_and_typed(self) -> None:
        settings = Settings(evaluation_reference_date="2026-07-15")
        self.assertEqual(settings.evaluation_reference_date, date(2026, 7, 15))

    def test_orchestration_runtime_is_restricted(self) -> None:
        self.assertEqual(Settings().agent_framework, "langchain")
        self.assertEqual(Settings().orchestration_runtime, "langgraph")
        self.assertEqual(
            Settings(orchestration_runtime="langgraph").orchestration_runtime,
            "langgraph",
        )
        with self.assertRaises(ValidationError):
            Settings(orchestration_runtime="unknown")


if __name__ == "__main__":
    unittest.main()
