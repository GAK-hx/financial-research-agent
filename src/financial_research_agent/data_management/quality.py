from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol, TypeVar

from financial_research_agent.data_management.models import DataQualityResult, QualityIssue

Row = TypeVar("Row")


class QualityRule(Protocol[Row]):
    """A rule returns no issue when a row is accepted by that rule."""

    def __call__(self, row: Row, row_number: int) -> QualityIssue | None: ...


def evaluate_rows(rows: Iterable[Row], rules: Sequence[QualityRule[Row]]) -> DataQualityResult:
    issues: list[QualityIssue] = []
    checked = 0
    rejected: set[int] = set()
    for row_number, row in enumerate(rows):
        checked += 1
        for rule in rules:
            issue = rule(row, row_number)
            if issue is not None:
                issues.append(issue)
                if issue.severity.value == "error":
                    rejected.add(row_number)
    return DataQualityResult(
        checked_rows=checked,
        accepted_rows=checked - len(rejected),
        rejected_rows=len(rejected),
        issues=issues,
    )
