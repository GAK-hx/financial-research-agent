from __future__ import annotations

import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from financial_research_agent.api import create_app
from financial_research_agent.api_models import (
    HealthComponent,
    HealthResponse,
)
from financial_research_agent.config import Settings
from financial_research_agent.jobs.models import (
    AdmissionRejected,
    ClaimedJob,
    JobEvent,
    JobSnapshot,
    JobStatus,
)
from financial_research_agent.jobs.store import JobConflict
from financial_research_agent.jobs.worker import JobWorker
from tests.test_api import FakeRegistry, research_result

try:
    from sqlalchemy import delete, update

    from financial_research_agent.jobs.store import JobStore
    from financial_research_agent.persistence.database import (
        create_business_engine,
        create_session_factory,
    )
    from financial_research_agent.persistence.models import (
        ResearchJobRecord,
    )

    PERSISTENCE_AVAILABLE = True
except ModuleNotFoundError:
    PERSISTENCE_AVAILABLE = False


POSTGRES_TESTS = (
    PERSISTENCE_AVAILABLE
    and os.environ.get("RUN_POSTGRES_TESTS", "").lower()
    in {"1", "true", "yes"}
)


def now() -> datetime:
    return datetime.now(timezone.utc)


def snapshot(
    *,
    run_id: str = "job-api-1",
    status: JobStatus = JobStatus.COMPLETED,
) -> JobSnapshot:
    timestamp = now()
    return JobSnapshot(
        run_id=run_id,
        status=status,
        question="分析贵州茅台财务",
        tenant_id="local",
        user_id="local",
        session_id="default",
        attempt_no=1,
        cancel_requested=False,
        created_at=timestamp,
        updated_at=timestamp,
        finished_at=(
            timestamp
            if status
            in {
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }
            else None
        ),
        result_available=False,
    )


class FakeJobStore:
    def __init__(self) -> None:
        self.job = snapshot()
        self.closed = False
        self.enqueue_kwargs = None

    async def enqueue(self, **kwargs):
        self.enqueue_kwargs = kwargs
        self.job = self.job.model_copy(
            update={
                "tenant_id": kwargs["tenant_id"],
                "user_id": kwargs["user_id"],
                "session_id": kwargs["session_id"],
                "queue_class": kwargs.get("queue_class", "interactive"),
            }
        )
        return self.job, True

    async def get(self, run_id, **kwargs):
        return self.job if run_id == self.job.run_id else None

    async def result(self, run_id, **kwargs):
        return None

    async def events(self, run_id, **kwargs):
        if run_id != self.job.run_id:
            raise JobConflict("JOB_NOT_FOUND")
        return [
            JobEvent(
                event_id=1,
                source="job",
                event_type="job_queued",
                payload={"status": "queued"},
                created_at=now(),
            ),
            JobEvent(
                event_id=2,
                source="job",
                event_type="job_terminal",
                payload={"status": "completed"},
                created_at=now(),
            ),
        ]

    async def request_cancel(self, run_id, **kwargs):
        raise JobConflict("ILLEGAL_CANCEL_TRANSITION")

    async def resume(self, run_id, **kwargs):
        raise JobConflict("ILLEGAL_RESUME_TRANSITION")

    async def trace(self, run_id, **kwargs):
        return {
            "run_id": run_id,
            "nodes": [],
            "model_calls": [],
            "tool_calls": [],
            "contexts": [],
        }

    async def metrics(self):
        return {
            "jobs": {"completed": 1},
            "model_calls": 2,
            "model_tokens": 100,
            "model_cost_microunits": 20,
            "tool_calls": 1,
            "admission": {"accepted:none": 1},
            "oldest_queue_age_seconds": 0.0,
            "active_workers": 0,
        }

    async def close(self):
        self.closed = True


class RejectingJobStore(FakeJobStore):
    async def enqueue(self, **kwargs):
        raise AdmissionRejected(
            "USER_QUEUE_LIMIT", retry_after_seconds=7
        )


class JobApiTests(unittest.TestCase):
    def client(self, *, settings=None, store=None):
        application = create_app()
        application.state.settings = settings or Settings()
        application.state.job_store = store or FakeJobStore()
        application.state.health_override = HealthResponse(
            status="degraded",
            version="0.1.0",
            model_configured=False,
            components={
                "configuration": HealthComponent(status="ready")
            },
        )
        return TestClient(application)

    def test_job_create_status_events_trace_skills_and_metrics(self):
        with self.client() as client:
            created = client.post(
                "/runs",
                headers={"Idempotency-Key": "api-job-key"},
                json={"question": "分析贵州茅台财务"},
            )
            run_id = created.json()["job"]["run_id"]
            status = client.get(f"/runs/{run_id}")
            events = client.get(f"/runs/{run_id}/events.json?after=1")
            stream = client.get(
                f"/runs/{run_id}/events",
                headers={"Last-Event-ID": "1"},
            )
            trace = client.get(f"/runs/{run_id}/trace")
            skills = client.get("/skills")
            metrics = client.get("/metrics")
        self.assertEqual(created.status_code, 202)
        self.assertEqual(status.json()["job"]["status"], "completed")
        self.assertEqual(
            [item["event_id"] for item in events.json()["events"]], [2]
        )
        self.assertNotIn("id: 1", stream.text)
        self.assertIn("id: 2", stream.text)
        self.assertEqual(trace.json()["run_id"], run_id)
        self.assertTrue(skills.json()["skills"])
        self.assertIn("financial_agent_jobs", metrics.text)

    def test_illegal_cancel_and_resume_return_conflict(self):
        with self.client() as client:
            cancel = client.post("/runs/job-api-1/cancel")
            resume = client.post("/runs/job-api-1/resume")
        self.assertEqual(cancel.status_code, 409)
        self.assertEqual(resume.status_code, 409)

    def test_sync_compatibility_times_out_to_background_job(self):
        store = FakeJobStore()
        store.job = snapshot(status=JobStatus.QUEUED)
        settings = Settings(
            analyze_via_jobs=True,
            analyze_sync_wait_seconds=0.1,
            job_sse_poll_interval_seconds=0.1,
        )
        with self.client(settings=settings, store=store) as client:
            response = client.post(
                "/analyze",
                headers={"Idempotency-Key": "sync-timeout-key"},
                json={"question": "分析贵州茅台财务"},
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            response.headers["location"], "/runs/job-api-1"
        )
        self.assertEqual(
            response.json()["job"]["status"], "queued"
        )

    def test_queue_overload_returns_retryable_429(self):
        with self.client(store=RejectingJobStore()) as client:
            response = client.post(
                "/runs", json={"question": "分析贵州茅台财务"}
            )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "7")
        self.assertEqual(
            response.json()["detail"]["code"], "USER_QUEUE_LIMIT"
        )

    def test_api_key_identity_is_resolved_from_headers_not_body(self):
        store = FakeJobStore()
        settings = Settings(identity_mode="api_key", agent_api_key="test-key")
        headers = {
            "Authorization": "Bearer test-key",
            "X-Tenant-ID": "tenant-a",
            "X-User-ID": "user-a",
            "Idempotency-Key": "scoped-key",
        }
        with self.client(settings=settings, store=store) as client:
            missing = client.post(
                "/runs", json={"question": "分析贵州茅台财务"}
            )
            created = client.post(
                "/runs",
                headers=headers,
                json={"question": "分析贵州茅台财务"},
            )
            rejected_body_identity = client.post(
                "/runs",
                headers=headers,
                json={
                    "question": "分析贵州茅台财务",
                    "tenant_id": "tenant-b",
                },
            )
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(created.status_code, 202)
        self.assertEqual(store.enqueue_kwargs["tenant_id"], "tenant-a")
        self.assertEqual(store.enqueue_kwargs["user_id"], "user-a")
        self.assertEqual(rejected_body_identity.status_code, 422)


class FakeWorkerStore:
    worker_id = "unit-worker"

    def __init__(self) -> None:
        self.completed = None

    async def claim(self):
        return ClaimedJob(
            run_id="worker-job-1",
            question="分析贵州茅台财务",
            tenant_id="local",
            user_id="local",
            session_id="default",
            attempt_no=1,
            lease_owner=self.worker_id,
            lease_expires_at=now() + timedelta(seconds=30),
        )

    async def renew(self, run_id):
        return True

    async def get(self, run_id):
        return snapshot(run_id=run_id, status=JobStatus.RUNNING)

    async def complete(self, run_id, **kwargs):
        self.completed = (run_id, kwargs)

    async def interrupt(self, run_id, error):
        raise AssertionError(error)


class FakeWorkerService:
    async def analyze(self, question, **kwargs):
        result = research_result()
        result.orchestration.run_id = kwargs["run_id"]
        return result


class HangingWorkerService:
    async def analyze(self, question, **kwargs):
        await asyncio.sleep(5)


class LeaseLostStore(FakeWorkerStore):
    def __init__(self) -> None:
        super().__init__()
        self.interrupted = None

    async def interrupt(self, run_id, error):
        self.interrupted = (run_id, error)


class LeaseLosingWorker(JobWorker):
    async def _heartbeat(self, run_id, lease_lost):
        lease_lost.set()


class JobWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_claims_and_completes_job(self):
        store = FakeWorkerStore()
        worker = JobWorker(
            Settings(orchestration_runtime="langgraph"),
            store=store,
            service=FakeWorkerService(),
            registry=FakeRegistry(),
        )
        worker.registry = FakeRegistry()
        self.assertTrue(await worker.run_once())
        self.assertEqual(store.completed[0], "worker-job-1")
        self.assertEqual(
            store.completed[1]["status"], JobStatus.COMPLETED
        )

    async def test_worker_cancels_research_when_database_lease_is_lost(self):
        store = LeaseLostStore()
        worker = LeaseLosingWorker(
            Settings(orchestration_runtime="langgraph"),
            store=store,
            service=HangingWorkerService(),
            registry=FakeRegistry(),
        )
        worker.registry = FakeRegistry()
        self.assertTrue(await worker.run_once())
        self.assertIsNone(store.completed)
        self.assertEqual(store.interrupted[0], "worker-job-1")
        self.assertIn("JOB_LEASE_LOST", store.interrupted[1])


@unittest.skipUnless(
    POSTGRES_TESTS, "Set RUN_POSTGRES_TESTS=1 for PostgreSQL job integration"
)
class PostgresJobStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.settings = Settings(
            business_database_url=os.environ["BUSINESS_DATABASE_URL"]
        )
        self.engine = create_business_engine(self.settings)
        sessions = create_session_factory(self.engine)
        self.one = JobStore(
            self.engine,
            sessions,
            worker_id=f"one-{uuid4().hex}",
            lease_seconds=30,
        )
        self.two = JobStore(
            self.engine,
            sessions,
            worker_id=f"two-{uuid4().hex}",
            lease_seconds=30,
        )
        self.run_ids: list[str] = []
        async with sessions.begin() as session:
            await session.execute(
                delete(ResearchJobRecord).where(
                    (
                        ResearchJobRecord.tenant_id.like("test-%")
                        | (ResearchJobRecord.tenant_id == "tenant")
                    )
                )
            )

    async def asyncTearDown(self) -> None:
        async with create_session_factory(self.engine).begin() as session:
            if self.run_ids:
                await session.execute(
                    delete(ResearchJobRecord).where(
                        ResearchJobRecord.run_id.in_(self.run_ids)
                    )
                )
        await self.engine.dispose()

    async def enqueue(self, key: str | None = None) -> JobSnapshot:
        job, _ = await self.one.enqueue(
            question="分析贵州茅台财务",
            tenant_id="test-jobs",
            user_id="user",
            session_id="session",
            idempotency_key=key or uuid4().hex,
        )
        self.run_ids.append(job.run_id)
        return job

    async def test_idempotency_and_two_worker_atomic_claim(self):
        key = uuid4().hex
        first = await self.enqueue(key)
        replay, created = await self.two.enqueue(
            question="分析贵州茅台财务",
            tenant_id="test-jobs",
            user_id="user",
            session_id="session",
            idempotency_key=key,
        )
        self.assertFalse(created)
        self.assertEqual(first.run_id, replay.run_id)
        with self.assertRaises(JobConflict):
            await self.two.enqueue(
                question="不同输入",
                tenant_id="test-jobs",
                user_id="user",
                session_id="session",
                idempotency_key=key,
            )
        claims = await asyncio.gather(self.one.claim(), self.two.claim())
        self.assertEqual(sum(item is not None for item in claims), 1)
        claimed = next(item for item in claims if item is not None)
        owner = self.one if claimed.lease_owner == self.one.worker_id else self.two
        self.assertTrue(await owner.renew(first.run_id))

    async def test_expired_lease_recovery_cancel_and_resume(self):
        first = await self.enqueue()
        claimed = await self.one.claim()
        self.assertIsNotNone(claimed)
        async with create_session_factory(self.engine).begin() as session:
            await session.execute(
                update(ResearchJobRecord)
                .where(ResearchJobRecord.run_id == first.run_id)
                .values(
                    lease_expires_at=now() - timedelta(seconds=1)
                )
            )
        recovered = await self.two.claim()
        self.assertEqual(recovered.run_id, first.run_id)
        self.assertEqual(recovered.attempt_no, 2)
        await self.two.interrupt(first.run_id, "controlled interruption")
        resumed = await self.one.resume(first.run_id)
        self.assertEqual(resumed.status, JobStatus.QUEUED)
        self.assertEqual(
            (await self.one.resume(first.run_id)).status,
            JobStatus.QUEUED,
        )
        cancelled = await self.one.request_cancel(first.run_id)
        self.assertEqual(cancelled.status, JobStatus.CANCELLED)
        self.assertEqual(
            (await self.two.request_cancel(first.run_id)).status,
            JobStatus.CANCELLED,
        )

    async def test_terminal_events_are_redacted(self):
        job = await self.enqueue()
        await self.one.claim()
        await self.one.complete(
            job.run_id,
            status=JobStatus.COMPLETED,
            result_payload={
                "success": True,
                "tool_status": [
                    {
                        "task_id": "financial",
                        "tool_name": "financial_query",
                        "success": True,
                        "authorization": "Bearer secret",
                    }
                ],
                "budget": {
                    "committed": {"tool_calls": 1, "tokens": 100},
                    "reasoning": "must never stream",
                },
            },
        )
        events = await self.one.events(job.run_id)
        rendered = " ".join(
            str(item.model_dump(mode="json")) for item in events
        )
        self.assertNotIn("Bearer secret", rendered)
        self.assertNotIn("must never stream", rendered)
        self.assertIn("'tokens': 100", rendered)
        self.assertIn("tool_completed", rendered)
        self.assertIn("budget_snapshot", rendered)

    async def test_tenant_scoped_access_and_tenant_scoped_idempotency(self):
        key = uuid4().hex
        first, _ = await self.one.enqueue(
            question="分析贵州茅台财务",
            tenant_id="test-scope-a",
            user_id="user-a",
            session_id="session",
            idempotency_key=key,
        )
        second, _ = await self.one.enqueue(
            question="分析贵州茅台财务",
            tenant_id="test-scope-b",
            user_id="user-b",
            session_id="session",
            idempotency_key=key,
        )
        self.run_ids.extend([first.run_id, second.run_id])
        self.assertNotEqual(first.run_id, second.run_id)
        self.assertIsNone(
            await self.one.get(
                first.run_id,
                tenant_id="test-scope-b",
                user_id="user-b",
            )
        )
        self.assertIsNone(
            await self.one.get(
                first.run_id,
                tenant_id="test-scope-a",
                user_id="other-user",
            )
        )
        self.assertIsNotNone(
            await self.one.get(
                first.run_id,
                tenant_id="test-scope-a",
                user_id="other-user",
                tenant_admin=True,
            )
        )
        with self.assertRaises(JobConflict):
            await self.one.events(
                first.run_id,
                tenant_id="test-scope-b",
                user_id="user-b",
            )

    async def test_queue_backpressure_and_tenant_running_fairness(self):
        settings = Settings(
            business_database_url=os.environ["BUSINESS_DATABASE_URL"],
            job_global_queue_limit=10,
            job_tenant_queue_limit=4,
            job_user_queue_limit=1,
            job_global_running_limit=2,
            job_tenant_running_limit=1,
            job_user_running_limit=1,
        )
        store = JobStore(
            self.engine,
            create_session_factory(self.engine),
            worker_id=f"fair-{uuid4().hex}",
            lease_seconds=30,
            settings=settings,
        )
        first, _ = await store.enqueue(
            question="分析贵州茅台财务",
            tenant_id="test-fair-a",
            user_id="user-a",
            session_id="session",
            idempotency_key=uuid4().hex,
        )
        self.run_ids.append(first.run_id)
        with self.assertRaises(AdmissionRejected) as rejected:
            await store.enqueue(
                question="分析宁德时代财务",
                tenant_id="test-fair-a",
                user_id="user-a",
                session_id="session",
                idempotency_key=uuid4().hex,
            )
        self.assertEqual(rejected.exception.code, "USER_QUEUE_LIMIT")
        second, _ = await store.enqueue(
            question="分析宁德时代财务",
            tenant_id="test-fair-b",
            user_id="user-b",
            session_id="session",
            idempotency_key=uuid4().hex,
        )
        self.run_ids.append(second.run_id)
        claims = [await store.claim(), await store.claim()]
        self.assertTrue(all(item is not None for item in claims))
        self.assertEqual(
            {item.tenant_id for item in claims},
            {"test-fair-a", "test-fair-b"},
        )


if __name__ == "__main__":
    unittest.main()
