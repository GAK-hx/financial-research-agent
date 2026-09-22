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
    "STEP8_GATE_BASE_URL", "http://127.0.0.1:8080/api/v1"
).rstrip("/")
TIMEOUT_SECONDS = float(os.environ.get("STEP8_GATE_TIMEOUT_SECONDS", "30"))
ARTIFACTS_ROOT = Path(os.environ.get("ARTIFACTS_ROOT", "artifacts"))

# Gate-only credentials. They are intentionally non-secret and must match the
# temporary GATEWAY_API_CLIENTS value used by the runbook.
CASES = (
    {
        "case_id": "tenant-a-analyst-1",
        "credential": "step8-key-a1",
        "tenant_id": "step8-tenant-a",
        "user_id": "analyst-1",
        "stock_codes": ["600519", "300750", "601318", "600036", "601166"],
    },
    {
        "case_id": "tenant-a-analyst-2",
        "credential": "step8-key-a2",
        "tenant_id": "step8-tenant-a",
        "user_id": "analyst-2",
        "stock_codes": ["600519", "300750", "600900", "601899", "600030"],
    },
    {
        "case_id": "tenant-b-analyst-1",
        "credential": "step8-key-b1",
        "tenant_id": "step8-tenant-b",
        "user_id": "analyst-1",
        "stock_codes": ["600519", "600036", "601088", "600276", "000001"],
    },
    {
        "case_id": "tenant-c-analyst-1",
        "credential": "step8-key-c1",
        "tenant_id": "step8-tenant-c",
        "user_id": "analyst-1",
        "stock_codes": ["300750", "601318", "000333", "000651", "000858"],
    },
    {
        "case_id": "tenant-d-analyst-1",
        "credential": "step8-key-d1",
        "tenant_id": "step8-tenant-d",
        "user_id": "analyst-1",
        "stock_codes": ["600519", "300750", "002594", "002415", "002475"],
    },
)


def headers(case: dict, idempotency_key: str | None = None) -> dict[str, str]:
    result = {"Authorization": f"Bearer {case['credential']}"}
    if idempotency_key:
        result["Idempotency-Key"] = idempotency_key
    return result


def question(stock_code: str) -> str:
    return (
        f"分析股票 {stock_code} 的近期趋势与主要风险，只使用可追踪数据，"
        "明确数据时点，不给出买卖建议。"
    )


async def post_one(
    client: httpx.AsyncClient,
    case: dict,
    stock_code: str,
    idempotency_key: str,
) -> dict:
    started = time.perf_counter()
    response = await client.post(
        "/runs",
        headers=headers(case, idempotency_key),
        json={"question": question(stock_code), "queue_class": "interactive"},
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text[:1000]}
    job = body.get("job") or {}
    return {
        "case_id": case["case_id"],
        "tenant_id": case["tenant_id"],
        "user_id": case["user_id"],
        "stock_code": stock_code,
        "idempotency_key": idempotency_key,
        "status_code": response.status_code,
        "elapsed_ms": elapsed_ms,
        "created": body.get("created"),
        "run_id": job.get("run_id"),
        "job_tenant_id": job.get("tenant_id"),
        "job_user_id": job.get("user_id"),
        "error": body.get("error") or body.get("detail"),
    }


async def get_status(
    client: httpx.AsyncClient, case: dict, run_id: str
) -> httpx.Response:
    return await client.get(f"/runs/{run_id}", headers=headers(case))


async def burst_one(case: dict, stock_code: str, idempotency_key: str) -> dict:
    # A dedicated connection per request makes the burst reproducible instead
    # of letting one keep-alive pool serialize requests on some host runtimes.
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        timeout=httpx.Timeout(TIMEOUT_SECONDS),
        trust_env=False,
    ) as client:
        return await post_one(client, case, stock_code, idempotency_key)


async def main() -> None:
    gate_tag = f"step8-{uuid4().hex[:12]}"
    jobs = [
        (case, stock_code, f"{gate_tag}-{case['case_id']}-{stock_code}")
        for case in CASES
        for stock_code in case["stock_codes"]
    ]
    async with httpx.AsyncClient(
        base_url=BASE_URL,
        timeout=httpx.Timeout(TIMEOUT_SECONDS),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=30),
        trust_env=False,
    ) as client:
        admission = await asyncio.gather(
            *(post_one(client, case, stock, key) for case, stock, key in jobs)
        )
        await asyncio.sleep(2.2)
        replay = await asyncio.gather(
            *(post_one(client, case, stock, key) for case, stock, key in jobs)
        )

        accepted = [item for item in admission if item["status_code"] == 202]
        replay_by_key = {item["idempotency_key"]: item for item in replay}
        idempotency_errors = []
        for original in accepted:
            duplicate = replay_by_key.get(original["idempotency_key"])
            if (
                duplicate is None
                or duplicate["status_code"] != 202
                or duplicate["created"] is not False
                or duplicate["run_id"] != original["run_id"]
            ):
                idempotency_errors.append(original["idempotency_key"])

        await asyncio.sleep(2.2)
        burst_case, burst_stock, burst_key = jobs[0]
        burst = await asyncio.gather(
            *(burst_one(burst_case, burst_stock, burst_key) for _ in range(15))
        )

        source = accepted[0] if accepted else None
        isolation = {
            "same_tenant_cross_user_status": None,
            "cross_tenant_status": None,
            "passed": False,
        }
        if source:
            same_tenant = CASES[1]
            cross_tenant = CASES[2]
            same_response, cross_response = await asyncio.gather(
                get_status(client, same_tenant, source["run_id"]),
                get_status(client, cross_tenant, source["run_id"]),
            )
            isolation = {
                "same_tenant_cross_user_status": same_response.status_code,
                "cross_tenant_status": cross_response.status_code,
                "passed": same_response.status_code == 404
                and cross_response.status_code == 404,
            }

        cancel_results = []
        case_by_id = {case["case_id"]: case for case in CASES}
        for item in accepted:
            response = await client.post(
                f"/runs/{item['run_id']}/cancel",
                headers=headers(case_by_id[item["case_id"]]),
            )
            body = response.json()
            cancel_results.append(
                {
                    "run_id": item["run_id"],
                    "status_code": response.status_code,
                    "job_status": (body.get("job") or {}).get("status"),
                }
            )

    identity_errors = [
        item["idempotency_key"]
        for item in accepted
        if item["tenant_id"] != item["job_tenant_id"]
        or item["user_id"] != item["job_user_id"]
    ]
    burst_202 = sum(item["status_code"] == 202 for item in burst)
    burst_429 = sum(item["status_code"] == 429 for item in burst)
    burst_run_ids = {item["run_id"] for item in burst if item["status_code"] == 202}
    passed = all(
        (
            len(admission) == 25,
            len(accepted) == 25,
            not identity_errors,
            not idempotency_errors,
            isolation["passed"],
            burst_202 > 0,
            burst_429 > 0,
            burst_202 + burst_429 == 15,
            burst_run_ids == ({source["run_id"]} if source else set()),
            len(cancel_results) == 25,
            all(
                item["status_code"] == 200
                and item["job_status"] == "cancelled"
                for item in cancel_results
            ),
        )
    )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "gateway_multiuser_admission_no_model_execution",
        "gate_tag": gate_tag,
        "passed": passed,
        "summary": {
            "users": len(CASES),
            "logical_jobs": len(jobs),
            "unique_stock_codes": len(
                {stock for case in CASES for stock in case["stock_codes"]}
            ),
            "admission_202": len(accepted),
            "identity_errors": len(identity_errors),
            "idempotency_errors": len(idempotency_errors),
            "burst_202": burst_202,
            "burst_429": burst_429,
            "cancelled": sum(
                item["job_status"] == "cancelled" for item in cancel_results
            ),
        },
        "isolation": isolation,
        "admission": admission,
        "replay": replay,
        "burst": burst,
        "cancel_results": cancel_results,
    }
    target = ARTIFACTS_ROOT / "step8"
    target.mkdir(parents=True, exist_ok=True)
    (target / "gateway_multiuser_gate.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = payload["summary"]
    lines = [
        "# Step 08.3 Gateway 多用户交叉查询 Gate",
        "",
        f"- 时间：{payload['generated_at']}",
        f"- 结论：`{'PASS' if passed else 'FAIL'}`",
        "- 模式：仅验证接入、队列与隔离；Worker 暂停，不调用模型。",
        f"- 用户：{summary['users']}；逻辑任务：{summary['logical_jobs']}；"
        f"股票覆盖：{summary['unique_stock_codes']} 支。",
        f"- 首次接收：{summary['admission_202']}/25；取消："
        f"{summary['cancelled']}/25。",
        f"- 幂等错误：{summary['idempotency_errors']}；身份错误："
        f"{summary['identity_errors']}。",
        f"- 单用户瞬时 15 请求：202={summary['burst_202']}，"
        f"429={summary['burst_429']}。",
        f"- 同租户跨用户读取：HTTP "
        f"{isolation['same_tenant_cross_user_status']}；跨租户读取：HTTP "
        f"{isolation['cross_tenant_status']}。",
    ]
    (target / "gateway_multiuser_gate.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(json.dumps({"passed": passed, **summary}, ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
