from __future__ import annotations

import re
from datetime import timedelta

from financial_research_agent.domain.models import (
    QuerySpec,
    SemanticAlignmentResult,
)
from financial_research_agent.orchestration.interpreter import QueryInterpreter


class SemanticAlignmentValidator:
    """Validate that structured scope still means what the resolved question asks."""

    def __init__(self, interpreter: QueryInterpreter) -> None:
        self.interpreter = interpreter

    def validate(self, question: str, query: QuerySpec) -> SemanticAlignmentResult:
        errors: list[str] = []
        warnings: list[str] = []
        expected = self.interpreter.interpret(question)

        if query.stock_codes != expected.stock_codes:
            errors.append(
                "ENTITY_SCOPE_MISMATCH:"
                f"expected={expected.stock_codes}:actual={query.stock_codes}"
            )
        if query.intent != expected.intent:
            errors.append(
                f"INTENT_SCOPE_MISMATCH:expected={expected.intent}:actual={query.intent}"
            )
        if set(query.dimensions) != set(expected.dimensions):
            errors.append(
                "DIMENSION_SCOPE_MISMATCH:"
                f"expected={sorted(expected.dimensions)}:actual={sorted(query.dimensions)}"
            )
        if query.analysis_domains != expected.analysis_domains:
            errors.append(
                "ANALYSIS_DOMAIN_SCOPE_MISMATCH:"
                f"expected={expected.analysis_domains}:actual={query.analysis_domains}"
            )

        scope = query.time_scope
        expected_scope = expected.time_scope
        if scope is None:
            errors.append("TIME_SCOPE_MISSING")
        else:
            if (query.start_date, query.end_date) != (
                scope.start_date,
                scope.end_date,
            ):
                errors.append("TIME_SCOPE_QUERY_RANGE_MISMATCH")
            if expected_scope is not None and (
                scope.kind,
                scope.granularity,
                scope.quantity,
                scope.start_date,
                scope.end_date,
                scope.complete_period,
                scope.calendar,
            ) != (
                expected_scope.kind,
                expected_scope.granularity,
                expected_scope.quantity,
                expected_scope.start_date,
                expected_scope.end_date,
                expected_scope.complete_period,
                expected_scope.calendar,
            ):
                errors.append("TIME_SCOPE_SEMANTIC_MISMATCH")
            self._validate_period_boundaries(scope, errors)

        if expected_scope and expected_scope.kind == "default_window":
            if re.search(r"(?:最近|近|近期|最新)", question):
                errors.append("TIME_EXPRESSION_AMBIGUOUS")
            else:
                warnings.append("TIME_SCOPE_DEFAULTED_TO_ONE_YEAR")
        if expected_scope and expected_scope.kind == "not_applicable":
            warnings.append("TIME_SCOPE_NOT_APPLICABLE")

        return SemanticAlignmentResult(
            passed=not errors,
            errors=errors,
            warnings=warnings,
            extracted_stock_codes=expected.stock_codes,
            expected_intent=expected.intent,
            expected_dimensions=expected.dimensions,
            expected_analysis_domains=expected.analysis_domains,
            resolved_time_expression=scope,
        )

    @staticmethod
    def _validate_period_boundaries(scope, errors: list[str]) -> None:
        if not scope.complete_period:
            return
        if scope.start_date is None or scope.end_date is None:
            errors.append("COMPLETE_PERIOD_RANGE_MISSING")
            return
        if scope.granularity == "day":
            if scope.start_date.weekday() >= 5 or scope.end_date.weekday() >= 5:
                errors.append("COMPLETE_TRADING_DAY_WEEKEND")
        elif scope.granularity == "month":
            if scope.start_date.day != 1 or (scope.end_date + timedelta(days=1)).day != 1:
                errors.append("COMPLETE_MONTH_BOUNDARY_MISMATCH")
        elif scope.granularity == "quarter":
            if scope.start_date.day != 1 or scope.start_date.month not in {1, 4, 7, 10}:
                errors.append("COMPLETE_QUARTER_START_MISMATCH")
            next_day = scope.end_date + timedelta(days=1)
            if next_day.day != 1 or next_day.month not in {1, 4, 7, 10}:
                errors.append("COMPLETE_QUARTER_END_MISMATCH")
        elif scope.granularity == "year":
            if (scope.start_date.month, scope.start_date.day) != (1, 1):
                errors.append("COMPLETE_YEAR_START_MISMATCH")
            if (scope.end_date.month, scope.end_date.day) != (12, 31):
                errors.append("COMPLETE_YEAR_END_MISMATCH")
