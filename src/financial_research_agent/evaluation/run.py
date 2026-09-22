from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from financial_research_agent.config import get_settings
from financial_research_agent.evaluation.models import (
    EvaluationArtifact,
    EvaluationCase,
    EvaluationDataset,
)
from financial_research_agent.evaluation.scoring import aggregate, score_case
from financial_research_agent.evaluation.stability import stability_report


DATASETS = {
    "regression": "cases.json",
    "holdout": "holdout_cases.json",
    "stability": "stability_cases.json",
}


def load_dataset() -> tuple[str, list[EvaluationCase]]:
    dataset, _ = load_named_dataset("regression")
    cases = dataset.cases
    if len(cases) != 20 or len({case.case_id for case in cases}) != 20:
        raise ValueError("core evaluation dataset must contain 20 unique cases")
    return dataset.dataset_version, cases


def load_named_dataset(name: str) -> tuple[EvaluationDataset, str]:
    if name == "private_holdout":
        configured = os.environ.get("EVAL_PRIVATE_HOLDOUT_PATH", "").strip()
        if not configured:
            raise ValueError(
                "private_holdout requires EVAL_PRIVATE_HOLDOUT_PATH"
            )
        path = Path(configured)
    elif name in DATASETS:
        path = Path(__file__).with_name(DATASETS[name])
    else:
        raise ValueError(f"unknown evaluation dataset: {name}")
    raw = path.read_bytes()
    dataset = EvaluationDataset.model_validate_json(raw)
    expected_counts = {"regression": 20, "holdout": 30, "stability": 10}
    expected = expected_counts.get(name)
    if dataset.kind != name:
        raise ValueError(
            f"dataset kind mismatch: expected {name}, got {dataset.kind}"
        )
    unique_count = len({case.case_id for case in dataset.cases})
    invalid_count = (
        len(dataset.cases) != unique_count
        or (expected is not None and len(dataset.cases) != expected)
        or (name == "private_holdout" and not 20 <= len(dataset.cases) <= 100)
    )
    if invalid_count:
        raise ValueError(
            f"{name} dataset has an invalid case count or duplicate IDs"
        )
    return dataset, hashlib.sha256(raw).hexdigest()


async def _request_case(
    client: httpx.AsyncClient,
    case: EvaluationCase,
    *,
    retries: int,
    retry_seconds: float,
) -> tuple[int, dict[str, Any], str | None]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = await client.post(
                "/analyze",
                json={
                    "question": case.question,
                    "tenant_id": "evaluation-tenant",
                    "user_id": "runner",
                    "session_id": f"{case.case_id}-isolated",
                },
                headers={
                    "Idempotency-Key": (
                        f"evaluation-{case.case_id}-{attempt}-"
                        f"{datetime.now(timezone.utc).timestamp()}"
                    )
                },
            )
            body = response.json()
            if response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"server returned {response.status_code}",
                    request=response.request,
                    response=response,
                )
            return (
                response.status_code,
                body,
                response.headers.get("x-request-id"),
            )
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            await asyncio.sleep(min(retry_seconds * (2**attempt), 60))
    assert last_error is not None
    return (
        0,
        {
            "error": {
                "code": "EVALUATION_REQUEST_FAILED",
                "message": f"{type(last_error).__name__}:{last_error}",
            }
        },
        None,
    )


def _operational_metrics(artifacts: list[EvaluationArtifact]) -> dict[str, Any]:
    tokens = 0
    cost = 0
    tool_calls = 0
    evidence = 0
    for artifact in artifacts:
        body = artifact.response
        committed = (body.get("budget") or {}).get("committed") or {}
        tokens += int(committed.get("tokens", 0))
        cost += int(committed.get("cost_microunits", 0))
        tool_calls += len(body.get("tool_status") or [])
        evidence += len(body.get("evidence") or [])
    return {
        "tokens": tokens,
        "cost_microunits": cost,
        "tool_calls": tool_calls,
        "evidence_count": evidence,
    }


def _failure_markdown(artifacts: list[EvaluationArtifact]) -> str:
    failed = [item for item in artifacts if not item.score.task_success]
    lines = [
        "# 评测失败用例原始输出",
        "",
        f"失败数：{len(failed)}/{len(artifacts)}",
        "",
    ]
    for artifact in failed:
        lines.extend(
            [
                f"## {artifact.case.case_id} / repetition {artifact.repetition}",
                "",
                f"- 问题：{artifact.case.question or '<empty>'}",
                f"- HTTP：{artifact.http_status}",
                f"- 评分错误：{', '.join(artifact.score.errors) or 'none'}",
                "",
                "```json",
                json.dumps(
                    artifact.response,
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


async def run() -> None:
    base_url = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
    dataset_name = os.environ.get("EVAL_DATASET", "regression").strip()
    repetitions = int(
        os.environ.get(
            "EVAL_REPETITIONS",
            "3" if dataset_name == "stability" else "1",
        )
    )
    if repetitions < 1 or repetitions > 10:
        raise ValueError("EVAL_REPETITIONS must be between 1 and 10")
    selected = {
        item.strip()
        for item in os.environ.get("EVAL_CASES", "").split(",")
        if item.strip()
    }
    dataset, dataset_sha256 = load_named_dataset(dataset_name)
    all_cases = dataset.cases
    summary_only = os.environ.get("EVAL_SUMMARY_ONLY", "").lower() in {"1", "true", "yes"}
    dataset_as_of = dataset.as_of_date
    active_settings = get_settings()
    if not summary_only and active_settings.evaluation_reference_date != dataset_as_of:
        raise ValueError(
            "full evaluation requires EVALUATION_REFERENCE_DATE="
            f"{dataset_as_of.isoformat()} to make relative dates reproducible"
        )
    snapshot_manifest = None
    if not summary_only:
        snapshot_path = os.environ.get("EVAL_SNAPSHOT_MANIFEST", "").strip()
        if not snapshot_path:
            raise ValueError(
                "full evaluation requires EVAL_SNAPSHOT_MANIFEST"
            )
        from financial_research_agent.evaluation.snapshot import (
            load_and_verify_manifest,
            verify_current_inputs,
        )

        snapshot_manifest = load_and_verify_manifest(
            Path(snapshot_path),
            dataset_sha256=dataset_sha256,
            as_of_date=dataset_as_of,
        )
        verify_current_inputs(active_settings, snapshot_manifest)
    cases = all_cases
    if selected:
        cases = [case for case in cases if case.case_id in selected or case.category in selected]
        unknown = selected - {case.case_id for case in cases} - {case.category for case in cases}
        if unknown:
            raise ValueError(f"unknown evaluation selectors: {sorted(unknown)}")
    if summary_only:
        cases = []
    root = (
        Path(active_settings.artifacts_root)
        / "agent_evaluation"
        / dataset_name
    )
    run_label = os.environ.get("EVAL_RUN_LABEL", "").strip()
    if run_label:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", run_label):
            raise ValueError("EVAL_RUN_LABEL contains unsupported characters")
        root = root / run_label
    runs_root = root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    artifacts: list[EvaluationArtifact] = []
    responses_for_stability: list[tuple[str, int, dict[str, Any]]] = []
    request_retries = int(os.environ.get("EVAL_HTTP_RETRIES", "3"))
    request_retry_seconds = float(
        os.environ.get("EVAL_HTTP_RETRY_SECONDS", "5")
    )
    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=active_settings.run_timeout_seconds + 30,
    ) as client:
        for repetition in range(1, repetitions + 1):
            repetition_root = runs_root / f"repeat-{repetition}"
            repetition_root.mkdir(parents=True, exist_ok=True)
            for case in cases:
                status, body, request_id = await _request_case(
                    client,
                    case,
                    retries=request_retries,
                    retry_seconds=request_retry_seconds,
                )
                score = score_case(case, status, body)
                artifact = EvaluationArtifact(
                    dataset_version=dataset.dataset_version,
                    dataset_sha256=dataset_sha256,
                    repetition=repetition,
                    case=case,
                    http_status=status,
                    request_id=request_id,
                    response=body,
                    score=score,
                )
                (repetition_root / f"{case.case_id}.json").write_text(
                    artifact.model_dump_json(indent=2), encoding="utf-8"
                )
                artifacts.append(artifact)
                responses_for_stability.append(
                    (case.case_id, repetition, body)
                )
                print(
                    json.dumps(
                        {
                            "case_id": case.case_id,
                            "repetition": repetition,
                            "category": case.category,
                            "task_success": score.task_success,
                            "api_total_ms": score.api_total_ms,
                            "errors": score.errors,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    scores = [artifact.score for artifact in artifacts]
    report = {
        "dataset": dataset_name,
        "dataset_version": dataset.dataset_version,
        "dataset_sha256": dataset_sha256,
        "dataset_frozen_at": dataset.frozen_at,
        "snapshot_manifest": (
            {
                "path": snapshot_path,
                "fingerprint": snapshot_manifest.fingerprint,
            }
            if snapshot_manifest is not None
            else None
        ),
        "evaluation_reference_date": (
            active_settings.evaluation_reference_date.isoformat()
            if active_settings.evaluation_reference_date
            else None
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": active_settings.model_name,
        "orchestration_runtime": active_settings.orchestration_runtime,
        "prompt_versions": {
            "planner": active_settings.planner_prompt_version,
            "report": active_settings.report_prompt_version,
        },
        "repetitions": repetitions,
        "executed_cases": [
            f"{artifact.case.case_id}#{artifact.repetition}"
            for artifact in artifacts
        ],
        "summary": aggregate(scores),
        "operational": _operational_metrics(artifacts),
        "case_scores": [score.model_dump(mode="json") for score in scores],
    }
    if dataset_name == "stability":
        report["stability"] = stability_report(
            responses_for_stability
        )
    report_path = root / "evaluation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "FAILED_CASES.md").write_text(
        _failure_markdown(artifacts), encoding="utf-8"
    )
    print(
        json.dumps(
            {"report": str(report_path), **report["summary"]},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(run())
