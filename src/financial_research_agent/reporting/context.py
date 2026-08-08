from __future__ import annotations

import json
from typing import Any

from financial_research_agent.domain.models import Evidence, QuerySpec


def _compact_data(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            key: _compact_data(value)
            for key, value in data.items()
            if key not in {"rows"}
        }
    if isinstance(data, list):
        return [_compact_data(value) for value in data[:20]]
    return data


def build_report_context(
    query: QuerySpec, evidence: list[Evidence], max_chars: int
) -> dict:
    items = [
        {
            "evidence_id": item.evidence_id,
            "type": item.evidence_type,
            "subject": item.subject,
            "statement": item.statement,
            "data": _compact_data(item.data),
            "source": {
                "type": item.source.source_type,
                "locator": item.source.locator,
                "metadata": item.source.metadata,
            },
        }
        for item in evidence
    ]
    payload = {"query": query.model_dump(mode="json"), "evidence": items}
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded) > max_chars:
        raise ValueError(f"report context exceeds {max_chars} characters")
    return payload
