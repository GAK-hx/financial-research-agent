from __future__ import annotations

import asyncio
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from uuid import uuid4

import httpx
from sqlalchemy import delete, func, select

from financial_research_agent.api import create_app
from financial_research_agent.config import Settings
from financial_research_agent.jobs.models import JobStatus
from financial_research_agent.jobs.store import JobStore
from financial_research_agent.persistence.database import (
    create_business_engine,
    create_session_factory,
)
from financial_research_agent.persistence.models import (
    JobEventRecord,
    ModelCallRecord,
    ResearchJobRecord,
)


LEVELS = (1, 10, 30, 50)
AUTH_CREDENTIAL = "step4-frozen-load-credential"


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return round(ordered[index], 3)


def frozen_result(run_id: str, elapsed_ms: int) -> dict:
    return {
        "success": True,
        "run_id": run_id,
        "planner_source": "frozen_stub",
        "selected_skills": [],
        "skill_selection_reason": "Step 4 queue benchmark",
        "policy_version": "financial_read_only_v1",
        "budget": None,
        "completion": None,
        "memory_scope": None,
        "memory_warnings": [],
        "context_manifests": {},
        "semantic_alignment": None,
        "execution_metadata": None,
        "reporting_status": "stub_complete",
        "query_spec": None,
        "plan": None,
        "tool_status": [],
        "evidence": [],
        "report": None,
        "validation": None,
        "timings": {"stub_execution": elapsed_ms},
        "metadata": {
            "model_provider": "frozen_stub",
            "model_name": None,
            "planner_prompt_version": "none",
            "report_prompt_version": "none",
            "tool_versions": {},
        },
        "error": None,
    }


async def worker_loop(store: JobStore, counter: dict, target: int) -> None:
    while counter["completed"] < target:
        job = await store.claim()
        if job is None:
            await asyncio.sleep(0.002)
            continue
        started = time.perf_counter()
        await asyncio.sleep(0.015)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        await store.complete(
            job.run_id,
            status=JobStatus.COMPLETED,
            result_payload=frozen_result(job.run_id, elapsed_ms),
        )
        counter["completed"] += 1


async def run_level(settings: Settings, level: int) -> dict:
    engine = create_business_engine(settings)
    sessions = create_session_factory(engine)
    api_store = JobStore(engine, sessions, settings=settings)
    app = create_app()
    app.state.settings = settings
    app.state.job_store = api_store
    stores = [
        JobStore(
            engine,
            sessions,
            settings=settings,
            worker_id=f"load-worker-{level}-{index}",
        )
        for index in range(settings.job_global_running_limit)
    ]
    prefix = f"bench-{level}-"
    async with sessions.begin() as session:
        await session.execute(
            delete(ResearchJobRecord).where(
                ResearchJobRecord.tenant_id.like(f"{prefix}%")
            )
        )
    transport = httpx.ASGITransport(app=app)
    accepts: list[float] = []
    first_events: list[float] = []
    run_ids: list[tuple[str, str, str]] = []
    counter = {"completed": 0}
    workers = [
        asyncio.create_task(worker_loop(store, counter, level))
        for store in stores
    ]
    started_all = time.perf_counter()
    async with httpx.AsyncClient(
        transport=transport, base_url="http://step4-gate"
    ) as client:
        async def submit(index: int) -> None:
            tenant = f"{prefix}{index % 5}"
            user = f"user-{index}"
            headers = {
                "Authorization": f"Bearer {AUTH_CREDENTIAL}",
                "X-Tenant-ID": tenant,
                "X-User-ID": user,
                "Idempotency-Key": f"{level}-{index}-{uuid4().hex}",
            }
            started = time.perf_counter()
            response = await client.post(
                "/runs",
                headers=headers,
                json={
                    "question": "冻结并发基准：分析贵州茅台",
                    "queue_class": "interactive",
                },
            )
            accepts.append((time.perf_counter() - started) * 1000)
            response.raise_for_status()
            run_id = response.json()["job"]["run_id"]
            event_response = await client.get(
                f"/runs/{run_id}/events.json", headers=headers
            )
            event_response.raise_for_status()
            if event_response.json()["events"]:
                first_events.append((time.perf_counter() - started) * 1000)
            run_ids.append((run_id, tenant, user))

        await asyncio.gather(*(submit(index) for index in range(level)))
        queue_waits: list[float] = []
        totals: list[float] = []
        while len(totals) < level:
            totals.clear()
            queue_waits.clear()
            for run_id, tenant, user in run_ids:
                job = await api_store.get(
                    run_id, tenant_id=tenant, user_id=user
                )
                if job is not None and job.status == JobStatus.COMPLETED:
                    totals.append(float(job.total_ms or 0))
                    queue_waits.append(float(job.queue_wait_ms or 0))
            if len(totals) < level:
                await asyncio.sleep(0.005)
    await asyncio.gather(*workers)
    wall_seconds = time.perf_counter() - started_all
    ids = [item[0] for item in run_ids]
    async with sessions() as session:
        db_completed = int(
            await session.scalar(
                select(func.count(ResearchJobRecord.run_id)).where(
                    ResearchJobRecord.run_id.in_(ids),
                    ResearchJobRecord.status == JobStatus.COMPLETED.value,
                )
            )
            or 0
        )
        terminal_rows = (
            await session.execute(
                select(
                    JobEventRecord.run_id,
                    func.count(JobEventRecord.id),
                )
                .where(
                    JobEventRecord.run_id.in_(ids),
                    JobEventRecord.event_type == "job_terminal",
                )
                .group_by(JobEventRecord.run_id)
            )
        ).all()
        provider_calls = int(
            await session.scalar(
                select(func.count(ModelCallRecord.id)).where(
                    ModelCallRecord.run_id.in_(ids)
                )
            )
            or 0
        )
    cross_tenant_leaks = 0
    for run_id, tenant, user in run_ids:
        leaked = await api_store.get(
            run_id,
            tenant_id=f"{tenant}-wrong",
            user_id=user,
        )
        cross_tenant_leaks += int(leaked is not None)
    duplicate_terminal = sum(
        max(0, int(count) - 1) for _, count in terminal_rows
    )
    result = {
        "virtual_users": level,
        "completed": counter["completed"],
        "errors": 0,
        "throughput_per_second": round(level / wall_seconds, 3),
        "api_accept_ms": {
            "p50": round(median(accepts), 3),
            "p95": percentile(accepts, 0.95),
            "p99": percentile(accepts, 0.99),
        },
        "first_event_ms": {
            "p50": round(median(first_events), 3),
            "p95": percentile(first_events, 0.95),
            "p99": percentile(first_events, 0.99),
        },
        "queue_wait_ms": {
            "p50": round(median(queue_waits), 3),
            "p95": percentile(queue_waits, 0.95),
            "p99": percentile(queue_waits, 0.99),
        },
        "total_ms": {
            "p50": round(median(totals), 3),
            "p95": percentile(totals, 0.95),
            "p99": percentile(totals, 0.99),
        },
        "invariants": {
            "lost_runs": level - db_completed,
            "duplicate_terminal": duplicate_terminal,
            "cross_tenant_leaks": cross_tenant_leaks,
            "provider_calls": provider_calls,
        },
    }
    async with sessions.begin() as session:
        await session.execute(
            delete(ResearchJobRecord).where(
                ResearchJobRecord.tenant_id.like(f"{prefix}%")
            )
        )
    await engine.dispose()
    return result


async def main() -> None:
    settings = Settings(
        identity_mode="api_key",
        agent_api_key=AUTH_CREDENTIAL,
        job_global_queue_limit=200,
        job_tenant_queue_limit=20,
        job_user_queue_limit=2,
        job_global_running_limit=8,
        job_tenant_running_limit=2,
        job_user_running_limit=1,
        provider_shared_rate_limit_enabled=False,
    )
    results = [await run_level(settings, level) for level in LEVELS]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "frozen_stub_no_model_network",
        "levels": results,
        "invariants": {
            key: sum(item["invariants"][key] for item in results)
            for key in (
                "lost_runs",
                "duplicate_terminal",
                "cross_tenant_leaks",
                "provider_calls",
            )
        },
    }
    target = Path(settings.artifacts_root) / "step4"
    target.mkdir(parents=True, exist_ok=True)
    (target / "load_test.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    rows = [
        "# Step 4 冻结并发基准",
        "",
        "本基准使用确定性 Stub，不调用模型网络；用于隔离 API、PostgreSQL Queue、",
        "公平领取和 Worker 调度开销。",
        "",
        "| VU | 完成 | 吞吐/s | API P95 ms | 首事件 P95 ms | 排队 P95 ms | 总耗时 P95 ms |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in results:
        rows.append(
            "| {virtual_users} | {completed} | {throughput_per_second} | "
            "{api_accept_ms[p95]} | {first_event_ms[p95]} | "
            "{queue_wait_ms[p95]} | {total_ms[p95]} |".format(**item)
        )
    rows.extend(
        [
            "",
            (
                "不变量：丢失 Run={lost_runs}、重复终态={duplicate_terminal}、"
                "跨租户泄漏={cross_tenant_leaks}、Provider 调用={provider_calls}。"
            ).format(**payload["invariants"]),
        ]
    )
    (target / "LOAD_TEST.md").write_text(
        "\n".join(rows) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
