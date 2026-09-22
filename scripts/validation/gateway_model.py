from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx


BASE_URL = os.environ.get(
    "GATEWAY_VALIDATION_BASE_URL", "http://127.0.0.1:8080/api/v1"
).rstrip("/")
TIMEOUT_SECONDS = int(os.environ.get("GATEWAY_MODEL_TIMEOUT_SECONDS", "900"))
ARTIFACTS_ROOT = Path(os.environ.get("ARTIFACTS_ROOT", "artifacts"))
ARTIFACT_BASENAME = os.environ.get(
    "GATEWAY_MODEL_ARTIFACT_BASENAME", "gateway_model_e2e"
)
CASES = (
    {
        "case_id": "single_technical",
        "credential": "gateway-key-a1",
        "question": (
            "分析 600519 在 2025-08-01 至 2026-08-07 的技术面，重点说明趋势、"
            "20日波动率、60日最大回撤和流动性风险。只使用日线数据，明确数据限制，"
            "不给出买卖建议。"
        ),
        "expected_codes": {"600519"},
    },
    {
        "case_id": "cross_stock_comparison",
        "credential": "gateway-key-b1",
        "question": (
            "比较 600519、300750 在 2025-08-01 至 2026-08-07 的技术面，重点说明"
            "趋势、20日波动率、60日最大回撤和流动性风险。只使用日线数据，"
            "明确数据限制，不给出买卖建议。"
        ),
        "expected_codes": {"600519", "300750"},
    },
)


def headers(case: dict, idempotency_key: str | None = None) -> dict[str, str]:
    value = {"Authorization": f"Bearer {case['credential']}"}
    if idempotency_key:
        value["Idempotency-Key"] = idempotency_key
    return value


async def run_case(client: httpx.AsyncClient, case: dict) -> dict:
    started = time.monotonic()
    response = await client.post(
        "/runs",
        headers=headers(case, f"gateway-flash-{case['case_id']}-{uuid4().hex}"),
        json={"question": case["question"], "queue_class": "interactive"},
    )
    body = response.json()
    record = {
        "case_id": case["case_id"],
        "question": case["question"],
        "submit_status": response.status_code,
        "submit_response": body,
    }
    if response.status_code != 202:
        record["assessment"] = {
            "passed": False,
            "errors": [f"submit_status={response.status_code}"],
        }
        return record
    run_id = body["job"]["run_id"]
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        terminal_response = await client.get(
            f"/runs/{run_id}", headers=headers(case)
        )
        terminal_response.raise_for_status()
        terminal = terminal_response.json()
        if terminal["job"]["status"] in {
            "completed",
            "failed",
            "cancelled",
        }:
            break
        await asyncio.sleep(2)
    else:
        terminal = {"job": {"run_id": run_id, "status": "timeout"}}
    events_response, trace_response = await asyncio.gather(
        client.get(f"/runs/{run_id}/events.json", headers=headers(case)),
        client.get(f"/runs/{run_id}/trace", headers=headers(case)),
    )
    record["terminal_response"] = terminal
    record["events"] = events_response.json().get("events", [])
    record["trace"] = trace_response.json()
    record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    result = terminal.get("result") or {}
    actual_codes = set((result.get("query_spec") or {}).get("stock_codes") or [])
    terminal_events = [
        event
        for event in record["events"]
        if event.get("event_type") == "job_terminal"
    ]
    errors = []
    if terminal["job"]["status"] != "completed":
        errors.append(f"job_status={terminal['job']['status']}")
    if result.get("success") is not True:
        errors.append("result_not_successful")
    if actual_codes != case["expected_codes"]:
        errors.append(f"stock_codes={sorted(actual_codes)}")
    model_name = (result.get("metadata") or {}).get("model_name")
    if model_name != "deepseek-flash":
        errors.append(f"model_name={model_name}")
    if len(terminal_events) != 1:
        errors.append(f"terminal_event_count={len(terminal_events)}")
    if not (record["trace"].get("model_calls") or []):
        errors.append("model_calls=0")
    record["assessment"] = {
        "passed": not errors,
        "errors": errors,
        "status": terminal["job"]["status"],
        "stock_codes": sorted(actual_codes),
        "model_name": model_name,
        "validation_passed": (result.get("validation") or {}).get("passed"),
        "model_calls": len(record["trace"].get("model_calls") or []),
        "tool_calls": len(record["trace"].get("tool_calls") or []),
    }
    return record


async def main() -> None:
    selected = {
        item.strip()
        for item in os.environ.get("GATEWAY_MODEL_CASES", "").split(",")
        if item.strip()
    }
    cases = tuple(
        case for case in CASES if not selected or case["case_id"] in selected
    )
    if not cases:
        raise SystemExit("GATEWAY_MODEL_CASES did not match a configured case")
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        timeout=httpx.Timeout(30),
        trust_env=False,
    ) as client:
        records = await asyncio.gather(*(run_case(client, case) for case in cases))
    passed = all(record["assessment"]["passed"] for record in records)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "deepseek-flash",
        "mode": "gateway_to_worker_full_e2e",
        "passed": passed,
        "records": records,
    }
    target = ARTIFACTS_ROOT / "gateway_validation"
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{ARTIFACT_BASENAME}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# DeepSeek Flash 网关端到端验证",
        "",
        f"- 时间：{payload['generated_at']}",
        f"- 模型：`{payload['model']}`",
        f"- 结论：`{'PASS' if passed else 'FAIL'}`",
        "",
        "| Case | 状态 | 股票 | 校验 | Model/Tool | 结果 |",
        "|---|---|---|---|---:|---|",
    ]
    for record in records:
        item = record["assessment"]
        lines.append(
            f"| {record['case_id']} | {item['status']} | "
            f"{','.join(item['stock_codes']) or '-'} | "
            f"{item['validation_passed']} | {item['model_calls']}/"
            f"{item['tool_calls']} | "
            f"{'通过' if item['passed'] else '; '.join(item['errors'])} |"
        )
    failures = [record for record in records if not record["assessment"]["passed"]]
    if failures:
        lines.extend(["", "## 失败原始输出", ""])
        for record in failures:
            lines.extend(
                [
                    f"### {record['case_id']}",
                    "",
                    "```json",
                    json.dumps(record, ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )
    (target / f"{ARTIFACT_BASENAME}.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "passed": passed,
                "results": [record["assessment"] for record in records],
            },
            ensure_ascii=False,
        )
    )
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
