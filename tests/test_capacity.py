from __future__ import annotations

import asyncio
import os
import unittest
from uuid import uuid4

from financial_research_agent.capacity.provider import (
    ProviderCapacity,
    ProviderCapacityExceeded,
)
from financial_research_agent.config import Settings


class ProviderCapacityTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_semaphore_bounds_parallel_requests(self):
        capacity = ProviderCapacity(
            Settings(
                provider_max_parallel_requests=1,
                provider_shared_rate_limit_enabled=False,
            )
        )
        active = 0
        maximum = 0

        async def enter():
            nonlocal active, maximum
            async with capacity.slot():
                active += 1
                maximum = max(maximum, active)
                await asyncio.sleep(0.01)
                active -= 1

        await asyncio.gather(enter(), enter(), enter())
        self.assertEqual(maximum, 1)


try:
    from sqlalchemy import delete

    from financial_research_agent.persistence.database import (
        create_business_engine,
        create_session_factory,
    )
    from financial_research_agent.persistence.models import (
        ProviderRateWindowRecord,
    )

    PERSISTENCE_AVAILABLE = True
except ModuleNotFoundError:
    PERSISTENCE_AVAILABLE = False


POSTGRES_TESTS = (
    PERSISTENCE_AVAILABLE
    and os.environ.get("RUN_POSTGRES_TESTS", "").lower()
    in {"1", "true", "yes"}
)


@unittest.skipUnless(
    POSTGRES_TESTS, "Set RUN_POSTGRES_TESTS=1 for PostgreSQL capacity integration"
)
class ProviderCapacityPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_instances_share_one_provider_rate_window(self):
        provider = f"test-provider-{uuid4().hex}"
        settings = Settings(
            business_database_url=os.environ["BUSINESS_DATABASE_URL"],
            model_provider=provider,
            provider_shared_rate_limit_enabled=True,
            provider_requests_per_minute=1,
            provider_rate_wait_seconds=0,
        )
        first = ProviderCapacity(settings)
        second = ProviderCapacity(settings)
        try:
            async with first.slot():
                pass
            with self.assertRaises(ProviderCapacityExceeded):
                async with second.slot():
                    pass
        finally:
            await first.aclose()
            await second.aclose()
            engine = create_business_engine(settings)
            async with create_session_factory(engine).begin() as session:
                await session.execute(
                    delete(ProviderRateWindowRecord).where(
                        ProviderRateWindowRecord.provider == provider
                    )
                )
            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
