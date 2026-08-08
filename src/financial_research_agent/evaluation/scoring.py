from __future__ import annotations

import math
from typing import Any

from financial_research_agent.domain.models import Evidence, QuerySpec, ResearchReport
from financial_research_agent.evaluation.models import CaseScore, EvaluationCase
from financial_research_agent.reporting.validators import ReportValidator


def _iso(value: Any) -> str | None:
    return str(value) if value is not None else None


def _model_call_count(body: dict[str, Any]) -> int:
    calls = 1 if body.get("planner_source") is not None else 0
    if body.get("reporting_status") is not None:
        calls += 1
    if "revise_report" in (body.get("timings") or {}):
        calls += 1
    return calls


def score_case(case: EvaluationCase, http_status: int, body: dict[str, Any]) -> CaseScore:
    errors: list[str] = []
    http_contract = http_status == case.expected_http_status
    if not http_contract:
        errors.append(f"HTTP_EXPECTED:{case.expected_http_status}:ACTUAL:{http_status}")

    actual_error = (body.get("error") or {}).get("code")
    if not case.expected_success:
        task_success = (
            http_contract
            and body.get("success") is not True
            and actual_error == case.expected_error_code
        )
        if not task_success:
            errors.append(
                f"REJECTION_EXPECTED:{case.expected_error_code}:ACTUAL:{actual_error}"
            )
        return CaseScore(
            case_id=case.case_id,
            category=case.category,
            http_contract=http_contract,
            task_success=task_success,
            api_total_ms=(body.get("timings") or {}).get("api_total"),
            model_calls=_model_call_count(body),
            errors=errors,
        )

    query = body.get("query_spec") or {}
    intent_accuracy = query.get("intent") == (
        case.expected_intent.value if case.expected_intent else None
    )
    if not intent_accuracy:
        errors.append(f"INTENT_EXPECTED:{case.expected_intent}:ACTUAL:{query.get('intent')}")

    tasks = (body.get("plan") or {}).get("tasks") or []
    actual_tools = {task.get("tool_name") for task in tasks}
    expected_tools = {tool.value for tool in case.expected_tools}
    tool_selection_accuracy = actual_tools == expected_tools
    if not tool_selection_accuracy:
        errors.append(
            f"TOOLS_EXPECTED:{sorted(expected_tools)}:ACTUAL:{sorted(actual_tools)}"
        )

    selected_skills = set(body.get("selected_skills") or [])
    expected_skills = set(case.expected_skills)
    skill_selection_accuracy = (
        selected_skills == expected_skills if expected_skills else True
    )
    if not skill_selection_accuracy:
        errors.append(
            f"SKILLS_EXPECTED:{sorted(expected_skills)}:"
            f"ACTUAL:{sorted(selected_skills)}"
        )

    expected_start = _iso(case.expected_start_date)
    expected_end = _iso(case.expected_end_date)
    query_arguments_match = (
        query.get("stock_codes") == case.expected_stock_codes
        and query.get("start_date") == expected_start
        and query.get("end_date") == expected_end
    )
    task_arguments_match = True
    expected_stock = case.expected_stock_codes[0]
    for task in tasks:
        arguments = task.get("arguments") or {}
        if arguments.get("stock_code") != expected_stock:
            task_arguments_match = False
        if "start_date" in arguments and arguments.get("start_date") != expected_start:
            task_arguments_match = False
        if "end_date" in arguments and arguments.get("end_date") != expected_end:
            task_arguments_match = False
    argument_accuracy = query_arguments_match and task_arguments_match
    if not argument_accuracy:
        errors.append("ARGUMENT_MISMATCH")

    alignment_payload = body.get("semantic_alignment") or {}
    semantic_alignment = alignment_payload.get("passed") is True
    if not semantic_alignment:
        errors.append(
            "SEMANTIC_ALIGNMENT_FAILED:"
            + ",".join(alignment_payload.get("errors") or ["missing"])
        )

    evidence_payload = body.get("evidence") or []
    evidence_types = {
        item.get("evidence_type") for item in evidence_payload
    }
    required_evidence = set(case.required_evidence_types)
    evidence_coverage = required_evidence.issubset(evidence_types)
    if not evidence_coverage:
        errors.append(
            f"EVIDENCE_EXPECTED:{sorted(required_evidence)}:"
            f"ACTUAL:{sorted(value for value in evidence_types if value)}"
        )
    evidence_ids = {item.get("evidence_id") for item in evidence_payload}
    report_payload = body.get("report") or {}
    claims = report_payload.get("claims") or []
    run_id = body.get("run_id") or ""
    citation_groups = [
        report_payload.get("summary_evidence_ids") or [],
        *[claim.get("evidence_ids") or [] for claim in claims],
        *[
            risk.get("evidence_ids") or []
            for risk in (report_payload.get("risks") or [])
            if isinstance(risk, dict)
        ],
    ]
    citation_accuracy = bool(claims) and all(
        group
        and set(group).issubset(evidence_ids)
        and all(value.startswith(f"{run_id}:") for value in group)
        for group in citation_groups
    )
    if not citation_accuracy:
        errors.append("CITATION_MISMATCH")

    numeric_consistency = False
    evidence_support_accuracy = False
    try:
        independent_validation = ReportValidator().validate(
            ResearchReport.model_validate(report_payload),
            QuerySpec.model_validate(query),
            [Evidence.model_validate(item) for item in evidence_payload],
            run_id,
        )
        numeric_consistency = not any(
            "NUMERIC_" in error for error in independent_validation.errors
        )
        evidence_support_accuracy = independent_validation.passed
    except Exception as exc:
        errors.append(f"INDEPENDENT_VALIDATION_ERROR:{type(exc).__name__}")
    if not numeric_consistency:
        errors.append("NUMERIC_INCONSISTENT")
    if not evidence_support_accuracy:
        errors.append("EVIDENCE_SUPPORT_INCOMPLETE")

    action_keys = [
        (
            task.get("tool_name"),
            str(sorted((task.get("arguments") or {}).items())),
        )
        for task in tasks
    ]
    duplicate_actions = len(action_keys) - len(set(action_keys))
    trajectory_redundancy = (
        round(duplicate_actions / len(action_keys), 4) if action_keys else 0.0
    )

    completion = body.get("completion") or {}
    completion_passed = (
        completion.get("passed") is True
        if case.require_harness_controls
        else completion.get("passed") is not False
    )
    if not completion_passed:
        errors.append("COMPLETION_NOT_PASSED")

    budget = body.get("budget") or {}
    budget_closed = (
        (
            budget.get("open_reservations") == 0
            if case.require_harness_controls
            else budget.get("open_reservations", 0) == 0
        )
        and budget.get("exceeded") is not True
    )
    if not budget_closed:
        errors.append("BUDGET_NOT_CLOSED")

    tools_succeeded = bool(tasks) and all(
        item.get("success") is True for item in (body.get("tool_status") or [])
    )
    task_success = (
        http_contract
        and body.get("success") is True
        and body.get("planner_source") == "model"
        and tools_succeeded
        and body.get("reporting_status") == "completed"
        and (body.get("validation") or {}).get("passed") is True
        and skill_selection_accuracy
        and semantic_alignment
        and evidence_coverage
        and evidence_support_accuracy
        and completion_passed
        and budget_closed
    )
    if not task_success:
        errors.append("TASK_NOT_COMPLETED")
    return CaseScore(
        case_id=case.case_id,
        category=case.category,
        http_contract=http_contract,
        intent_accuracy=intent_accuracy,
        tool_selection_accuracy=tool_selection_accuracy,
        skill_selection_accuracy=skill_selection_accuracy,
        argument_accuracy=argument_accuracy,
        semantic_alignment=semantic_alignment,
        evidence_coverage=evidence_coverage,
        citation_accuracy=citation_accuracy,
        numeric_consistency=numeric_consistency,
        evidence_support_accuracy=evidence_support_accuracy,
        completion_passed=completion_passed,
        budget_closed=budget_closed,
        trajectory_redundancy=trajectory_redundancy,
        task_success=task_success,
        planner_source=body.get("planner_source"),
        api_total_ms=(body.get("timings") or {}).get("api_total"),
        model_calls=_model_call_count(body),
        errors=errors,
    )


def percentile(values: list[int], quantile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return round(value)


def aggregate(scores: list[CaseScore]) -> dict[str, Any]:
    metric_names = (
        "intent_accuracy",
        "tool_selection_accuracy",
        "skill_selection_accuracy",
        "argument_accuracy",
        "semantic_alignment",
        "evidence_coverage",
        "citation_accuracy",
        "numeric_consistency",
        "evidence_support_accuracy",
        "completion_passed",
        "budget_closed",
        "task_success",
    )
    metrics: dict[str, dict[str, float | int]] = {}
    for name in metric_names:
        values = [getattr(score, name) for score in scores if getattr(score, name) is not None]
        passed = sum(value is True for value in values)
        metrics[name] = {
            "passed": passed,
            "total": len(values),
            "rate": round(passed / len(values), 4) if values else 0.0,
        }
    latencies = [
        score.api_total_ms
        for score in scores
        if score.category != "invalid" and score.api_total_ms is not None
    ]
    return {
        "case_count": len(scores),
        "metrics": metrics,
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "min": min(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "model_calls": sum(score.model_calls for score in scores),
        "trajectory_redundancy": (
            round(
                sum(score.trajectory_redundancy or 0.0 for score in scores)
                / len(scores),
                4,
            )
            if scores
            else 0.0
        ),
        "failed_cases": [score.case_id for score in scores if not score.task_success],
    }
