from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any


def _stable_locator(locator: str | None) -> str:
    if locator is None:
        return ""
    return locator.split("#", 1)[0]


def _numeric_values(value: Any, prefix: str = "") -> dict[str, float]:
    values: dict[str, float] = {}
    if isinstance(value, bool):
        return values
    if isinstance(value, (int, float)):
        values[prefix] = round(float(value), 10)
    elif isinstance(value, dict):
        for key, item in sorted(value.items()):
            if key in {
                "snapshot_id",
                "latency_ms",
                "token_estimate_before",
                "token_estimate_after",
            }:
                continue
            values.update(_numeric_values(item, f"{prefix}.{key}".strip(".")))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            values.update(_numeric_values(item, f"{prefix}[{index}]"))
    return values


def response_fingerprint(response: dict[str, Any]) -> dict[str, Any]:
    evidence = response.get("evidence") or []
    report = response.get("report") or {}
    return {
        "success": response.get("success"),
        "intent": (response.get("query_spec") or {}).get("intent"),
        "skills": sorted(response.get("selected_skills") or []),
        "tools": sorted(
            str(item["tool_name"])
            for item in (response.get("tool_status") or [])
            if item.get("tool_name") is not None
        ),
        "evidence": sorted(
            (
                str(item.get("evidence_type") or ""),
                str(item.get("subject") or ""),
                str((item.get("source") or {}).get("source_type") or ""),
                _stable_locator((item.get("source") or {}).get("locator")),
            )
            for item in evidence
        ),
        "numbers": _numeric_values(
            [
                {
                    "type": item.get("evidence_type"),
                    "subject": item.get("subject"),
                    "data": item.get("data") or {},
                }
                for item in evidence
            ]
        ),
        "report_structure": {
            "fields": sorted(report),
            "has_subjects": bool(report.get("subjects")),
            "has_summary": bool(report.get("summary")),
            "has_claims": bool(report.get("claims")),
            "has_risks": bool(report.get("risks")),
            "has_limitations_field": "limitations" in report,
            "has_data_as_of_field": "data_as_of" in report,
            "has_disclaimer": bool(report.get("disclaimer")),
        },
        "validation_passed": (
            (response.get("validation") or {}).get("passed")
        ),
        "completion_passed": (
            (response.get("completion") or {}).get("passed")
        ),
    }


def fingerprint_sha256(fingerprint: dict[str, Any]) -> str:
    payload = json.dumps(
        fingerprint, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def stability_report(
    responses: list[tuple[str, int, dict[str, Any]]]
) -> dict[str, Any]:
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for case_id, repetition, response in responses:
        grouped[case_id].append((repetition, response))
    case_reports: list[dict[str, Any]] = []
    dimensions = ("skills", "tools", "evidence", "numbers", "report_structure")
    dimension_passes = {dimension: 0 for dimension in dimensions}
    for case_id, runs in sorted(grouped.items()):
        ordered = sorted(runs)
        fingerprints = [
            response_fingerprint(response) for _, response in ordered
        ]
        checks = {
            dimension: all(
                item[dimension] == fingerprints[0][dimension]
                for item in fingerprints[1:]
            )
            for dimension in dimensions
        }
        for dimension, passed in checks.items():
            dimension_passes[dimension] += int(passed)
        case_reports.append(
            {
                "case_id": case_id,
                "repetitions": [repetition for repetition, _ in ordered],
                "checks": checks,
                "fully_stable": all(checks.values()),
                "fingerprint_sha256": [
                    fingerprint_sha256(item) for item in fingerprints
                ],
            }
        )
    total = len(case_reports)
    return {
        "case_count": total,
        "repetitions_per_case": (
            min((len(value) for value in grouped.values()), default=0)
        ),
        "dimension_rates": {
            name: round(value / total, 4) if total else 0.0
            for name, value in dimension_passes.items()
        },
        "fully_stable_cases": sum(
            item["fully_stable"] for item in case_reports
        ),
        "cases": case_reports,
    }
