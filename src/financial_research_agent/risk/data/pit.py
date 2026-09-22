from __future__ import annotations

from collections.abc import Iterable

from financial_research_agent.risk.domain.models import PointInTimeBoundary, RiskFact


def select_visible_facts(
    facts: Iterable[RiskFact], boundary: PointInTimeBoundary
) -> list[RiskFact]:
    """Return the latest visible revision per issuer, period and metric.

    ``as_of_date`` models when information became public. ``system_cutoff`` models
    when this system had ingested it. Keeping both prevents publication-time and
    ingestion-time leakage from being silently conflated.
    """

    latest: dict[tuple[str, object, str], RiskFact] = {}
    for fact in facts:
        if fact.source_published_at.date() > boundary.as_of_date:
            continue
        if fact.observed_at > boundary.system_cutoff:
            continue
        key = (fact.issuer_id, fact.report_period, fact.metric_code)
        current = latest.get(key)
        ordering = (fact.source_published_at, fact.revision_no, fact.observed_at)
        if current is None or ordering > (
            current.source_published_at,
            current.revision_no,
            current.observed_at,
        ):
            latest[key] = fact
    return sorted(
        latest.values(),
        key=lambda item: (item.issuer_id, item.report_period, item.metric_code),
    )
