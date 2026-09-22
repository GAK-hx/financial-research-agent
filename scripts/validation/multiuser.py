from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx


BASE_URL = os.environ.get("MULTIUSER_GATE_BASE_URL", "http://job-api:8000")
AUTH_CREDENTIAL = os.environ.get("AGENT_API_KEY", "")
POLL_SECONDS = float(os.environ.get("MULTIUSER_GATE_POLL_SECONDS", "2"))
TIMEOUT_SECONDS = int(os.environ.get("MULTIUSER_GATE_TIMEOUT_SECONDS", "900"))

CASES = (
    {
        "case_id": "tenant-a-analyst-1",
        "tenant_id": "validation-tenant-a",
        "user_id": "analyst-1",
        "stock_codes": ["600519", "300750", "601318", "600036"],
    },
    {
        "case_id": "tenant-a-analyst-2",
        "tenant_id": "validation-tenant-a",
        "user_id": "analyst-2",
        "stock_codes": ["600519", "300750", "601166", "600900", "601899"],
    },
    {
        "case_id": "tenant-b-analyst-1",
        "tenant_id": "validation-tenant-b",
        "user_id": "analyst-1",
        "stock_codes": ["600519", "600036", "600030", "601088"],
    },
    {
        "case_id": "tenant-c-analyst-1",
        "tenant_id": "validation-tenant-c",
        "user_id": "analyst-1",
        "stock_codes": ["300750", "601318", "600276", "000001", "000333"],
    },
    {
        "case_id": "tenant-d-analyst-1",
        "tenant_id": "validation-tenant-d",
        "user_id": "analyst-1",
        "stock_codes": ["600519", "300750", "000651", "000858", "002594"],
    },
)


def request_headers(case: dict) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {AUTH_CREDENTIAL}",
        "X-Tenant-ID": case["tenant_id"],
        "X-User-ID": case["user_id"],
        "X-Agent-Role": "researcher",
    }


def question(case: dict) -> str:
    codes = "、".join(case["stock_codes"])
    return (
        f"比较 {codes} 在 2025-08-01 至 2026-08-07 的技术面，"
        "重点说明趋势、20日波动率、最大回撤和流动性风险。"
        "只使用日线数据，明确数据限制，不给出买卖建议。"
    )


async def submit(client: httpx.AsyncClient, case: dict) -> dict:
    started = time.perf_counter()
    response = await client.post(
        "/runs",
        headers={
            **request_headers(case),
            "Idempotency-Key": f"multiuser-{case['case_id']}-{uuid4().hex}",
        },
        json={"question": question(case), "queue_class": "interactive"},
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    body = response.json()
    if response.status_code != 202:
        return {
            "case": case,
            "accepted": False,
            "submit_status": response.status_code,
            "submit_ms": elapsed_ms,
            "submit_response": body,
        }
    return {
        "case": case,
        "accepted": True,
        "submit_status": response.status_code,
        "submit_ms": elapsed_ms,
        "run_id": body["job"]["run_id"],
    }


async def wait_for_terminal(client: httpx.AsyncClient, record: dict) -> dict:
    if not record["accepted"]:
        return record
    case = record["case"]
    headers = request_headers(case)
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        response = await client.get(f"/runs/{record['run_id']}", headers=headers)
        response.raise_for_status()
        body = response.json()
        status = body["job"]["status"]
        if status in {"completed", "failed", "cancelled"}:
            record["terminal_response"] = body
            break
        await asyncio.sleep(POLL_SECONDS)
    else:
        record["timeout"] = True
        return record

    events_response, trace_response = await asyncio.gather(
        client.get(f"/runs/{record['run_id']}/events.json", headers=headers),
        client.get(f"/runs/{record['run_id']}/trace", headers=headers),
    )
    events_response.raise_for_status()
    trace_response.raise_for_status()
    record["events"] = events_response.json()["events"]
    record["trace"] = trace_response.json()
    return record


def assess(record: dict) -> dict:
    errors: list[str] = []
    if not record.get("accepted"):
        errors.append("submission_not_accepted")
        return {"passed": False, "errors": errors}
    if record.get("timeout"):
        errors.append("terminal_timeout")
        return {"passed": False, "errors": errors}
    terminal = record["terminal_response"]
    job = terminal["job"]
    result = terminal.get("result") or {}
    if job["status"] != "completed":
        errors.append(f"job_status={job['status']}")
    if result.get("success") is not True:
        errors.append("result_not_successful")
    actual_codes = (result.get("query_spec") or {}).get("stock_codes") or []
    if set(actual_codes) != set(record["case"]["stock_codes"]):
        errors.append(f"stock_codes_mismatch={actual_codes}")
    comparison_status = [
        item
        for item in result.get("tool_status") or []
        if item.get("tool_name") == "stock_comparison"
    ]
    if not comparison_status or not all(item.get("success") for item in comparison_status):
        errors.append("stock_comparison_not_successful")
    comparison_evidence = [
        item
        for item in result.get("evidence") or []
        if item.get("evidence_type") == "comparison"
    ]
    coverage = max(
        [int((item.get("data") or {}).get("coverage_count", 0)) for item in comparison_evidence],
        default=0,
    )
    if coverage != len(record["case"]["stock_codes"]):
        errors.append(f"comparison_coverage={coverage}")
    if (result.get("validation") or {}).get("passed") is not True:
        errors.append("report_validation_not_passed")
    terminal_events = [
        item for item in record.get("events", []) if item.get("event_type") == "job_terminal"
    ]
    if len(terminal_events) != 1:
        errors.append(f"terminal_event_count={len(terminal_events)}")
    return {
        "passed": not errors,
        "errors": errors,
        "stock_codes": actual_codes,
        "comparison_coverage": coverage,
        "status": job["status"],
        "queue_wait_ms": job.get("queue_wait_ms"),
        "execution_ms": job.get("execution_ms"),
        "total_ms": job.get("total_ms"),
        "model_calls": len((record.get("trace") or {}).get("model_calls") or []),
        "tool_calls": len((record.get("trace") or {}).get("tool_calls") or []),
    }


async def isolation_checks(client: httpx.AsyncClient, records: list[dict]) -> dict:
    source = next(item for item in records if item["case"]["case_id"] == "tenant-a-analyst-1")
    same_tenant_other_user = next(
        item for item in records if item["case"]["case_id"] == "tenant-a-analyst-2"
    )
    cross_tenant = next(
        item for item in records if item["case"]["case_id"] == "tenant-b-analyst-1"
    )
    headers = request_headers(source["case"])
    same_user_response, cross_tenant_response = await asyncio.gather(
        client.get(f"/runs/{same_tenant_other_user['run_id']}", headers=headers),
        client.get(f"/runs/{cross_tenant['run_id']}", headers=headers),
    )
    return {
        "same_tenant_cross_user_status": same_user_response.status_code,
        "cross_tenant_status": cross_tenant_response.status_code,
        "passed": same_user_response.status_code == 404
        and cross_tenant_response.status_code == 404,
    }


def markdown_report(payload: dict) -> str:
    lines = [
        "# 多用户真实查询验证",
        "",
        f"- 时间：{payload['generated_at']}",
        f"- 模式：{payload['mode']}",
        f"- 结论：`{'PASS' if payload['passed'] else 'FAIL'}`",
        f"- 用户查询：{len(payload['records'])}",
        f"- 总股票覆盖：{len(payload['unique_stock_codes'])} 支",
        "- 热点重复：600519 与 300750 分别被多个用户查询",
        "",
        "| Case | 租户/用户 | 股票数 | 结果 | 排队 ms | 执行 ms | 总耗时 ms | Model/Tool |",
        "|---|---|---:|---|---:|---:|---:|---:|",
    ]
    for record in payload["records"]:
        assessment = record["assessment"]
        lines.append(
            f"| {record['case']['case_id']} | {record['case']['tenant_id']}/"
            f"{record['case']['user_id']} | {len(record['case']['stock_codes'])} | "
            f"{'通过' if assessment['passed'] else '失败'} | "
            f"{assessment.get('queue_wait_ms', '-')} | {assessment.get('execution_ms', '-')} | "
            f"{assessment.get('total_ms', '-')} | {assessment.get('model_calls', '-')}/"
            f"{assessment.get('tool_calls', '-')} |"
        )
    lines.extend(
        [
            "",
            "## 隔离检查",
            "",
            f"- 同租户跨用户读取：HTTP {payload['isolation']['same_tenant_cross_user_status']}；",
            f"- 跨租户读取：HTTP {payload['isolation']['cross_tenant_status']}；",
        ]
    )
    failures = [item for item in payload["records"] if not item["assessment"]["passed"]]
    if failures:
        lines.extend(["", "## 失败原始输出", ""])
        for item in failures:
            lines.extend(
                [
                    f"### {item['case']['case_id']}",
                    "",
                    "```json",
                    json.dumps(item, ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )
    return "\n".join(lines) + "\n"


async def main() -> None:
    if not AUTH_CREDENTIAL:
        raise SystemExit("AGENT_API_KEY is required")
    timeout = httpx.Timeout(60.0, connect=20.0)
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=timeout) as client:
        health = await client.get("/health")
        health.raise_for_status()
        submitted = await asyncio.gather(*(submit(client, case) for case in CASES))
        records = await asyncio.gather(
            *(wait_for_terminal(client, record) for record in submitted)
        )
        for record in records:
            record["assessment"] = assess(record)
        accepted_records = [item for item in records if item.get("accepted")]
        isolation = (
            await isolation_checks(client, accepted_records)
            if len(accepted_records) == len(CASES)
            else {"passed": False, "reason": "not_all_runs_accepted"}
        )

    unique_codes = sorted({code for case in CASES for code in case["stock_codes"]})
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "five_concurrent_users_real_flash_real_market_evidence",
        "unique_stock_codes": unique_codes,
        "isolation": isolation,
        "records": records,
    }
    payload["passed"] = isolation.get("passed") is True and all(
        item["assessment"]["passed"] for item in records
    )
    target = Path(os.environ.get("ARTIFACTS_ROOT", "/artifacts")) / "multiuser_validation"
    target.mkdir(parents=True, exist_ok=True)
    (target / "multiuser.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (target / "MULTIUSER_VALIDATION.md").write_text(
        markdown_report(payload), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "passed": payload["passed"],
                "unique_stock_codes": unique_codes,
                "isolation": isolation,
                "records": [
                    {
                        "case_id": item["case"]["case_id"],
                        "run_id": item.get("run_id"),
                        "assessment": item["assessment"],
                    }
                    for item in records
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    raise SystemExit(0 if payload["passed"] else 1)


if __name__ == "__main__":
    asyncio.run(main())
