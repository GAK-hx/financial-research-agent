from __future__ import annotations

import asyncio
import math
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from financial_research_agent.config import Settings


class ProviderCapacityExceeded(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("PROVIDER_SHARED_RATE_LIMIT")
        self.retry_after_seconds = retry_after_seconds


class ProviderCapacity:
    """Bound local parallelism and optionally share a DB-backed minute budget."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.semaphore = asyncio.Semaphore(
            settings.provider_max_parallel_requests
        )
        self.engine = None
        self.sessions = None
        self.record_model = None
        if settings.provider_shared_rate_limit_enabled:
            from financial_research_agent.persistence.database import (
                create_business_engine,
                create_session_factory,
            )
            from financial_research_agent.persistence.models import (
                ProviderRateWindowRecord,
            )

            self.engine = create_business_engine(settings)
            self.sessions = create_session_factory(self.engine)
            self.record_model = ProviderRateWindowRecord

    @asynccontextmanager
    async def slot(self):
        async with self.semaphore:
            await self._reserve_shared_request()
            yield

    async def aclose(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()

    async def _reserve_shared_request(self) -> None:
        if self.sessions is None:
            return
        from sqlalchemy import select, text

        record_model = self.record_model
        assert record_model is not None
        waited = 0
        while True:
            now = datetime.now(timezone.utc)
            window = now.replace(second=0, microsecond=0)
            retry_after = max(1, math.ceil(60 - (now - window).total_seconds()))
            allowed = False
            async with self.sessions.begin() as session:
                await session.execute(
                    text(
                        "SELECT pg_advisory_xact_lock(hashtext(:lock_key))"
                    ),
                    {
                        "lock_key": (
                            "financial_agent:provider_rate:"
                            f"{self.settings.model_provider}"
                        )
                    },
                )
                record = await session.scalar(
                    select(record_model)
                    .where(
                        record_model.provider
                        == self.settings.model_provider,
                        record_model.window_started_at == window,
                    )
                    .with_for_update()
                )
                if record is None:
                    session.add(
                        record_model(
                            provider=self.settings.model_provider,
                            window_started_at=window,
                            request_count=1,
                            limited_count=0,
                        )
                    )
                    allowed = True
                elif record.request_count < (
                    self.settings.provider_requests_per_minute
                ):
                    record.request_count += 1
                    allowed = True
                else:
                    record.limited_count += 1
            if allowed:
                return
            if waited + retry_after > self.settings.provider_rate_wait_seconds:
                raise ProviderCapacityExceeded(retry_after)
            await asyncio.sleep(retry_after)
            waited += retry_after
