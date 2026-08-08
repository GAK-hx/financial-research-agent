from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_runs(root: Path) -> dict[str, dict[str, Any]]:
    runs: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("eval-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        case_id = payload["case"]["case_id"]
        runs[case_id] = payload
    return runs


def _fingerprint(artifact: dict[str, Any]) -> dict[str, Any]:
    response = artifact.get("response") or {}
    query = response.get("query_spec") or {}
    tool_status = response.get("tool_status") or []
    evidence = response.get("evidence") or []
    report = response.get("report")
    validation = response.get("validation")
    return {
        "http_status": artifact.get("http_status"),
        "task_success": artifact.get("score", {}).get("task_success", False),
        "response_success": response.get("success"),
        "intent": query.get("intent"),
        "stock_codes": query.get("stock_codes"),
        "tools": [item.get("tool_name") for item in tool_status],
        "tool_success": [item.get("success") for item in tool_status],
        "evidence_types": sorted(item.get("evidence_type") for item in evidence),
        "evidence_subjects": sorted(item.get("subject") for item in evidence),
        "report_present": report is not None,
        "report_fields": sorted(report) if isinstance(report, dict) else [],
        "validation_passed": (
            validation.get("passed") if isinstance(validation, dict) else None
        ),
        "error_code": (response.get("error") or {}).get("code"),
    }


def compare(baseline_root: Path, candidate_root: Path) -> dict[str, Any]:
    baseline = _load_runs(baseline_root)
    candidate = _load_runs(candidate_root)
    case_ids = sorted(set(baseline) | set(candidate))
    cases: list[dict[str, Any]] = []
    regressions: list[str] = []
    recoveries: list[str] = []
    stable_semantic_matches = 0
    stable_semantic_total = 0
    semantic_fields = (
        "intent",
        "stock_codes",
        "tools",
        "tool_success",
        "evidence_types",
        "evidence_subjects",
        "report_present",
        "report_fields",
        "validation_passed",
        "error_code",
    )
    for case_id in case_ids:
        if case_id not in baseline or case_id not in candidate:
            cases.append(
                {
                    "case_id": case_id,
                    "status": "missing",
                    "missing_from": (
                        "baseline" if case_id not in baseline else "candidate"
                    ),
                }
            )
            continue
        before = _fingerprint(baseline[case_id])
        after = _fingerprint(candidate[case_id])
        before_success = bool(before["task_success"])
        after_success = bool(after["task_success"])
        if before_success and not after_success:
            regressions.append(case_id)
        elif not before_success and after_success:
            recoveries.append(case_id)
        differences = {
            field: {"baseline": before[field], "candidate": after[field]}
            for field in semantic_fields
            if before[field] != after[field]
        }
        if before_success and after_success:
            stable_semantic_total += 1
            if not differences:
                stable_semantic_matches += 1
        cases.append(
            {
                "case_id": case_id,
                "baseline_task_success": before_success,
                "candidate_task_success": after_success,
                "semantic_differences": differences,
            }
        )
    return {
        "baseline_root": str(baseline_root),
        "candidate_root": str(candidate_root),
        "case_count": len(case_ids),
        "missing_count": sum(item.get("status") == "missing" for item in cases),
        "regressions": regressions,
        "recoveries": recoveries,
        "stable_semantic_matches": stable_semantic_matches,
        "stable_semantic_total": stable_semantic_total,
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare legacy and LangGraph evaluations.")
    parser.add_argument("baseline_runs", type=Path)
    parser.add_argument("candidate_runs", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = compare(args.baseline_runs, args.candidate_runs)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
