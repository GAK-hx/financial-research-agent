from __future__ import annotations

import asyncio
import logging
import os
import signal
from contextlib import suppress
from uuid import uuid4

from financial_research_agent.api import _analyze_response
from financial_research_agent.config import Settings, get_settings
from financial_research_agent.jobs.models import JobStatus
from financial_research_agent.jobs.store import JobConflict, JobStore
from financial_research_agent.observability import configure_logging, log_event
from financial_research_agent.orchestration.factory import (
    build_formal_registry,
)
from financial_research_agent.persistence.database import (
    create_business_engine,
    create_session_factory,
)
from financial_research_agent.research_factory import build_research_service

logger = logging.getLogger("financial_research_agent.worker")


class JobWorker:
    def __init__(
        self,
        settings: Settings,
        *,
        store: JobStore | None = None,
        service=None,
        registry=None,
    ) -> None:
        if settings.orchestration_runtime != "langgraph":
            raise ValueError("job worker requires ORCHESTRATION_RUNTIME=langgraph")
        self.settings = settings
        worker_id = (
            settings.job_worker_id
            or os.environ.get("HOSTNAME")
            or f"worker-{uuid4().hex[:12]}"
        )
        if store is None:
            engine = create_business_engine(settings)
            store = JobStore(
                engine,
                create_session_factory(engine),
                worker_id=worker_id,
                lease_seconds=settings.job_lease_seconds,
                settings=settings,
            )
        self.store = store
        self.service = service or build_research_service(settings)
        self.registry = registry or build_formal_registry(settings)
        self.stopping = asyncio.Event()

    async def run_once(self) -> bool:
        job = await self.store.claim()
        if job is None:
            return False
        log_event(
            logger,
            "job_claimed",
            run_id=job.run_id,
            worker_id=self.store.worker_id,
            attempt_no=job.attempt_no,
        )
        research = asyncio.create_task(
            self.service.analyze(
                job.question,
                run_id=job.run_id,
                tenant_id=job.tenant_id,
                user_id=job.user_id,
                session_id=job.session_id,
            )
        )
        lease_lost = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat(job.run_id, lease_lost)
        )
        lost_wait = asyncio.create_task(lease_lost.wait())
        try:
            done, _ = await asyncio.wait(
                {research, lost_wait}, return_when=asyncio.FIRST_COMPLETED
            )
            if lost_wait in done and lease_lost.is_set():
                research.cancel()
                with suppress(asyncio.CancelledError):
                    await research
                raise JobConflict("JOB_LEASE_LOST")
            result = await research
            if result.orchestration.run_id != job.run_id:
                raise JobConflict("WORKER_RESULT_RUN_ID_MISMATCH")
            job_state = await self.store.get(job.run_id)
            cancelled = (
                bool(job_state and job_state.cancel_requested)
                or "RUN_CANCELLED" in result.orchestration.errors
            )
            response = _analyze_response(
                result, self.settings, self.registry
            ).model_dump(mode="json")
            status = (
                JobStatus.CANCELLED
                if cancelled
                else (
                    JobStatus.COMPLETED
                    if result.success
                    else JobStatus.FAILED
                )
            )
            await self.store.complete(
                job.run_id,
                status=status,
                result_payload=response,
                last_error=(
                    None
                    if result.success
                    else ";".join(result.orchestration.errors)[:512]
                ),
            )
            log_event(
                logger,
                "job_completed",
                run_id=job.run_id,
                worker_id=self.store.worker_id,
                status=status.value,
                success=result.success,
            )
        except Exception as exc:
            log_event(
                logger,
                "job_interrupted",
                run_id=job.run_id,
                worker_id=self.store.worker_id,
                error_type=type(exc).__name__,
            )
            with suppress(JobConflict):
                await self.store.interrupt(
                    job.run_id, f"{type(exc).__name__}:{exc}"
                )
        finally:
            heartbeat.cancel()
            lost_wait.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            with suppress(asyncio.CancelledError):
                await lost_wait
        return True

    async def run_forever(self) -> None:
        tasks = [
            asyncio.create_task(
                self._slot_loop(slot_no),
                name=f"job-worker-slot-{slot_no}",
            )
            for slot_no in range(self.settings.job_worker_concurrency)
        ]
        await asyncio.gather(*tasks)

    async def _slot_loop(self, slot_no: int) -> None:
        while not self.stopping.is_set():
            worked = await self.run_once()
            if not worked:
                try:
                    await asyncio.wait_for(
                        self.stopping.wait(),
                        timeout=self.settings.job_poll_interval_seconds,
                    )
                except TimeoutError:
                    pass

    async def close(self) -> None:
        self.stopping.set()
        close = getattr(self.service, "aclose", None)
        if close is not None:
            await close()
        await self.store.close()

    async def _heartbeat(
        self, run_id: str, lease_lost: asyncio.Event
    ) -> None:
        interval = max(1.0, self.settings.job_lease_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            if not await self.store.renew(run_id):
                lease_lost.set()
                return


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    worker = JobWorker(settings)
    loop = asyncio.get_running_loop()
    for event in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(event, worker.stopping.set)
    log_event(
        logger,
        "worker_started",
        worker_id=worker.store.worker_id,
        lease_seconds=settings.job_lease_seconds,
        concurrency=settings.job_worker_concurrency,
    )
    try:
        await worker.run_forever()
    finally:
        await worker.close()
        log_event(
            logger,
            "worker_stopped",
            worker_id=worker.store.worker_id,
        )


if __name__ == "__main__":
    asyncio.run(main())
