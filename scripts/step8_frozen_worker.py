from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone

from financial_research_agent.config import Settings
from financial_research_agent.jobs.models import JobStatus
from financial_research_agent.jobs.store import JobStore
from financial_research_agent.persistence.database import (
    create_business_engine,
    create_session_factory,
)


def frozen_result(run_id: str) -> dict:
    return {
        "success": True,
        "run_id": run_id,
        "planner_source": "step8_frozen_worker",
        "selected_skills": [],
        "skill_selection_reason": "Step 08.3 lease recovery gate",
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
        "timings": {"stub_execution": 0},
        "metadata": {
            "model_provider": "frozen_stub",
            "model_name": None,
            "planner_prompt_version": "none",
            "report_prompt_version": "none",
            "tool_versions": {},
        },
        "error": None,
    }


async def run(mode: str, expected_run_id: str) -> None:
    settings = Settings(provider_shared_rate_limit_enabled=False)
    engine = create_business_engine(settings)
    sessions = create_session_factory(engine)
    worker_id = (
        "step8-crashed-worker" if mode == "claim-and-exit" else "step8-recovery-worker"
    )
    store = JobStore(
        engine,
        sessions,
        settings=settings,
        worker_id=worker_id,
        lease_seconds=30,
    )
    claimed = await store.claim()
    if claimed is None:
        raise RuntimeError("NO_JOB_AVAILABLE")
    if claimed.run_id != expected_run_id:
        raise RuntimeError(
            f"UNEXPECTED_JOB: expected={expected_run_id} actual={claimed.run_id}"
        )
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "run_id": claimed.run_id,
        "attempt_no": claimed.attempt_no,
        "worker_id": worker_id,
        "lease_expires_at": claimed.lease_expires_at.isoformat(),
    }
    if mode == "recover-one":
        await store.complete(
            claimed.run_id,
            status=JobStatus.COMPLETED,
            result_payload=frozen_result(claimed.run_id),
        )
        output["completed"] = True
    print(json.dumps(output, ensure_ascii=False))
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode", choices=("claim-and-exit", "recover-one")
    )
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.mode, args.run_id))


if __name__ == "__main__":
    main()
