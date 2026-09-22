from __future__ import annotations

import asyncio
import json
import os
import unittest

from financial_research_agent.config import Settings
from financial_research_agent.shared_state import RedisSharedState


class MemoryRedisClient:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.messages: list[tuple[str, str]] = []

    async def ping(self):
        return True

    async def aclose(self):
        return None

    async def set(self, key, value, *, ex=None, nx=False):
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def publish(self, channel, message):
        self.messages.append((channel, message))
        return 1

    async def zrem(self, key, token):
        del key, token
        return 1


class BrokenRedisClient:
    def __getattr__(self, _):
        async def fail(*args, **kwargs):
            del args, kwargs
            raise ConnectionError("offline")

        return fail


class RedisSharedStateUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_keys_hide_identity_and_hot_values_are_bounded(self):
        client = MemoryRedisClient()
        state = RedisSharedState(
            client,
            Settings(redis_enabled=True, redis_key_prefix="test-agent"),
        )
        key = state.key_for("idem", "tenant-secret", "request-key")
        self.assertNotIn("tenant-secret", key)
        self.assertEqual(key, state.key_for("idem", "tenant-secret", "request-key"))

        first = await state.remember_idempotency(
            "tenant-secret",
            "request-key",
            run_id="run-1",
            request_hash="hash-1",
        )
        second = await state.remember_idempotency(
            "tenant-secret",
            "request-key",
            run_id="run-2",
            request_hash="hash-2",
        )
        self.assertEqual(first.run_id, "run-1")
        self.assertEqual(second.run_id, "run-1")

        self.assertTrue(
            await state.set_metadata(
                "retrieval", "query-key", {"snapshot_id": "snapshot-1"}
            )
        )
        self.assertEqual(
            await state.get_metadata("retrieval", "query-key"),
            {"snapshot_id": "snapshot-1"},
        )
        self.assertTrue(
            await state.publish_job_event(
                "run-1", "job_terminal", {"status": "completed"}
            )
        )
        self.assertEqual(
            json.loads(client.messages[0][1])["event_type"], "job_terminal"
        )

    async def test_redis_failure_uses_explicit_degraded_policy(self):
        state = RedisSharedState(
            BrokenRedisClient(),
            Settings(redis_enabled=True, redis_fail_open=True),
        )
        rate = await state.rate_limit(
            "tenant:t1", capacity=5, refill_per_second=1
        )
        slot = await state.acquire_slot(
            "tenant:t1", limit=2, lease_seconds=10
        )
        self.assertTrue(rate.allowed)
        self.assertTrue(rate.degraded)
        self.assertEqual(rate.error_code, "REDIS_UNAVAILABLE")
        self.assertTrue(slot.acquired)
        self.assertTrue(slot.degraded)
        self.assertEqual(state.metrics["errors"], 2)


@unittest.skipUnless(os.getenv("REDIS_TEST_URL"), "requires real Redis")
class RedisSharedStateIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.state = RedisSharedState.from_settings(
            Settings(
                redis_enabled=True,
                redis_url=os.environ["REDIS_TEST_URL"],
                redis_password=os.getenv("REDIS_TEST_PASSWORD", ""),
                redis_key_prefix="financial-agent-validation",
            )
        )
        await self.state.client.flushdb()

    async def asyncTearDown(self):
        await self.state.client.flushdb()
        await self.state.aclose()

    async def test_atomic_rate_slots_idempotency_metadata_and_notification(self):
        rate_results = await asyncio.gather(
            *[
                self.state.rate_limit(
                    "tenant:t1", capacity=5, refill_per_second=0.01
                )
                for _ in range(20)
            ]
        )
        self.assertEqual(sum(item.allowed for item in rate_results), 5)

        slots = await asyncio.gather(
            *[
                self.state.acquire_slot(
                    "tenant:t1", limit=2, lease_seconds=30, token=f"slot-{index}"
                )
                for index in range(10)
            ]
        )
        self.assertEqual(sum(item.acquired for item in slots), 2)
        for item in slots:
            if item.acquired:
                await self.state.release_slot("tenant:t1", item.token)

        records = await asyncio.gather(
            *[
                self.state.remember_idempotency(
                    "tenant-t1",
                    "same-key",
                    run_id=f"run-{index}",
                    request_hash="same-hash",
                )
                for index in range(20)
            ]
        )
        self.assertEqual(len({item.run_id for item in records}), 1)

        await self.state.set_metadata(
            "analysis", "analysis-key", {"artifact_id": "artifact-1"}
        )
        self.assertEqual(
            (await self.state.get_metadata("analysis", "analysis-key"))[
                "artifact_id"
            ],
            "artifact-1",
        )

        channel = self.state.key_for("event", "run-1")
        async with self.state.client.pubsub() as pubsub:
            await pubsub.subscribe(channel)
            await self.state.publish_job_event(
                "run-1", "job_terminal", {"status": "completed"}
            )
            message = None
            for _ in range(20):
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=0.1
                )
                if message:
                    break
            self.assertIsNotNone(message)
            self.assertEqual(json.loads(message["data"])["event_type"], "job_terminal")
