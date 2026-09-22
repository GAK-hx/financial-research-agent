from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from financial_research_agent.config import Settings
from financial_research_agent.observability import log_event

logger = logging.getLogger("financial_research_agent.shared_state")


TOKEN_BUCKET_SCRIPT = """
local current = redis.call('TIME')
local now_ms = current[1] * 1000 + math.floor(current[2] / 1000)
local capacity = tonumber(ARGV[1])
local refill_per_ms = tonumber(ARGV[2]) / 1000
local cost = tonumber(ARGV[3])
local ttl_ms = tonumber(ARGV[4])
local values = redis.call('HMGET', KEYS[1], 'tokens', 'updated_ms')
local tokens = tonumber(values[1]) or capacity
local updated_ms = tonumber(values[2]) or now_ms
tokens = math.min(capacity, tokens + math.max(0, now_ms - updated_ms) * refill_per_ms)
local allowed = 0
local retry_ms = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
elseif refill_per_ms > 0 then
  retry_ms = math.ceil((cost - tokens) / refill_per_ms)
else
  retry_ms = ttl_ms
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'updated_ms', now_ms)
redis.call('PEXPIRE', KEYS[1], ttl_ms)
return {allowed, math.floor(tokens), retry_ms}
"""


ACQUIRE_SLOT_SCRIPT = """
local current = redis.call('TIME')
local now_ms = current[1] * 1000 + math.floor(current[2] / 1000)
local limit = tonumber(ARGV[1])
local lease_ms = tonumber(ARGV[2])
local token = ARGV[3]
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms)
if redis.call('ZCARD', KEYS[1]) >= limit then
  local earliest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  local retry_ms = lease_ms
  if earliest[2] then retry_ms = math.max(1, tonumber(earliest[2]) - now_ms) end
  return {0, redis.call('ZCARD', KEYS[1]), retry_ms}
end
redis.call('ZADD', KEYS[1], now_ms + lease_ms, token)
redis.call('PEXPIRE', KEYS[1], lease_ms + 1000)
return {1, redis.call('ZCARD', KEYS[1]), 0}
"""


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: float = 0.0
    degraded: bool = False
    error_code: str | None = None


@dataclass(frozen=True)
class SlotDecision:
    acquired: bool
    token: str
    active: int
    retry_after_seconds: float = 0.0
    degraded: bool = False
    error_code: str | None = None


@dataclass(frozen=True)
class IdempotencyRecord:
    run_id: str
    request_hash: str


class NoopSharedState:
    enabled = False

    async def ping(self) -> bool:
        return False

    async def aclose(self) -> None:
        return None

    async def rate_limit(self, *_, capacity: int, **__) -> RateLimitDecision:
        return RateLimitDecision(
            allowed=True,
            remaining=capacity,
            degraded=True,
            error_code="REDIS_DISABLED",
        )

    async def acquire_slot(self, *_, limit: int, **__) -> SlotDecision:
        return SlotDecision(
            acquired=True,
            token=uuid4().hex,
            active=0,
            degraded=True,
            error_code="REDIS_DISABLED",
        )

    async def release_slot(self, *_, **__) -> bool:
        return True

    async def remember_idempotency(self, *_, **__) -> IdempotencyRecord | None:
        return None

    async def get_idempotency(self, *_, **__) -> IdempotencyRecord | None:
        return None

    async def set_metadata(self, *_, **__) -> bool:
        return False

    async def get_metadata(self, *_, **__) -> dict[str, Any] | None:
        return None

    async def publish_job_event(self, *_, **__) -> bool:
        return False


class RedisSharedState:
    enabled = True

    def __init__(self, client, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self.prefix = settings.redis_key_prefix.strip(":") or "financial-agent"
        self.metrics: dict[str, int] = {
            "operations": 0,
            "errors": 0,
            "metadata_hits": 0,
            "metadata_misses": 0,
        }

    @classmethod
    def from_settings(cls, settings: Settings) -> RedisSharedState:
        from redis.asyncio import Redis

        client = Redis.from_url(
            settings.redis_url,
            password=settings.redis_password or None,
            decode_responses=True,
            protocol=2,
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            socket_timeout=settings.redis_socket_timeout_seconds,
            health_check_interval=30,
        )
        return cls(client, settings)

    @staticmethod
    def _digest(*parts: str) -> str:
        payload = "\x00".join(parts).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def key_for(self, kind: str, *parts: str) -> str:
        allowed = {"analysis", "event", "idem", "rate", "retrieval", "slot"}
        if kind not in allowed:
            raise ValueError(f"unsupported Redis key kind: {kind}")
        return f"{self.prefix}:v1:{kind}:{self._digest(*parts)}"

    async def ping(self) -> bool:
        try:
            return bool(await self.client.ping())
        except Exception as exc:
            self._record_error("ping", exc)
            return False

    async def aclose(self) -> None:
        await self.client.aclose()

    async def rate_limit(
        self,
        scope: str,
        *,
        capacity: int,
        refill_per_second: float,
        cost: int = 1,
        ttl_seconds: int = 120,
    ) -> RateLimitDecision:
        if capacity < 1 or refill_per_second < 0 or cost < 1:
            raise ValueError("invalid token bucket parameters")
        key = self.key_for("rate", scope)
        try:
            self.metrics["operations"] += 1
            allowed, remaining, retry_ms = await self.client.eval(
                TOKEN_BUCKET_SCRIPT,
                1,
                key,
                capacity,
                refill_per_second,
                cost,
                ttl_seconds * 1000,
            )
            return RateLimitDecision(
                allowed=bool(allowed),
                remaining=int(remaining),
                retry_after_seconds=float(retry_ms) / 1000,
            )
        except Exception as exc:
            return self._rate_limit_failure(capacity, exc)

    async def acquire_slot(
        self,
        scope: str,
        *,
        limit: int,
        lease_seconds: float,
        token: str | None = None,
    ) -> SlotDecision:
        if limit < 1 or lease_seconds <= 0:
            raise ValueError("invalid concurrency slot parameters")
        token = token or uuid4().hex
        key = self.key_for("slot", scope)
        try:
            self.metrics["operations"] += 1
            acquired, active, retry_ms = await self.client.eval(
                ACQUIRE_SLOT_SCRIPT,
                1,
                key,
                limit,
                int(lease_seconds * 1000),
                token,
            )
            return SlotDecision(
                acquired=bool(acquired),
                token=token,
                active=int(active),
                retry_after_seconds=float(retry_ms) / 1000,
            )
        except Exception as exc:
            self._record_error("acquire_slot", exc)
            return SlotDecision(
                acquired=self.settings.redis_fail_open,
                token=token,
                active=0,
                degraded=True,
                error_code="REDIS_UNAVAILABLE",
            )

    async def release_slot(self, scope: str, token: str) -> bool:
        try:
            self.metrics["operations"] += 1
            return bool(await self.client.zrem(self.key_for("slot", scope), token))
        except Exception as exc:
            self._record_error("release_slot", exc)
            return False

    async def remember_idempotency(
        self,
        tenant_id: str,
        idempotency_key: str,
        *,
        run_id: str,
        request_hash: str,
        ttl_seconds: int | None = None,
    ) -> IdempotencyRecord | None:
        redis_key = self.key_for("idem", tenant_id, idempotency_key)
        payload = json.dumps(
            {"run_id": run_id, "request_hash": request_hash},
            separators=(",", ":"),
        )
        try:
            self.metrics["operations"] += 1
            created = await self.client.set(
                redis_key,
                payload,
                ex=ttl_seconds or self.settings.redis_idempotency_ttl_seconds,
                nx=True,
            )
            if created:
                return IdempotencyRecord(run_id=run_id, request_hash=request_hash)
            return self._parse_idempotency(await self.client.get(redis_key))
        except Exception as exc:
            self._record_error("remember_idempotency", exc)
            return None

    async def get_idempotency(
        self, tenant_id: str, idempotency_key: str
    ) -> IdempotencyRecord | None:
        try:
            self.metrics["operations"] += 1
            value = await self.client.get(
                self.key_for("idem", tenant_id, idempotency_key)
            )
            return self._parse_idempotency(value)
        except Exception as exc:
            self._record_error("get_idempotency", exc)
            return None

    async def set_metadata(
        self,
        kind: str,
        identifier: str,
        payload: dict[str, Any],
        *,
        ttl_seconds: int | None = None,
    ) -> bool:
        if kind not in {"analysis", "retrieval"}:
            raise ValueError("metadata kind must be analysis or retrieval")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 16_384:
            raise ValueError("Redis metadata exceeds 16 KiB")
        try:
            self.metrics["operations"] += 1
            return bool(
                await self.client.set(
                    self.key_for(kind, identifier),
                    encoded,
                    ex=ttl_seconds or self.settings.redis_metadata_ttl_seconds,
                )
            )
        except Exception as exc:
            self._record_error("set_metadata", exc)
            return False

    async def get_metadata(
        self, kind: str, identifier: str
    ) -> dict[str, Any] | None:
        if kind not in {"analysis", "retrieval"}:
            raise ValueError("metadata kind must be analysis or retrieval")
        try:
            self.metrics["operations"] += 1
            value = await self.client.get(self.key_for(kind, identifier))
            if value is None:
                self.metrics["metadata_misses"] += 1
                return None
            result = json.loads(value)
            if not isinstance(result, dict):
                return None
            self.metrics["metadata_hits"] += 1
            return result
        except Exception as exc:
            self._record_error("get_metadata", exc)
            return None

    async def publish_job_event(
        self, run_id: str, event_type: str, payload: dict[str, Any] | None = None
    ) -> bool:
        message = json.dumps(
            {"run_id": run_id, "event_type": event_type, "payload": payload or {}},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            self.metrics["operations"] += 1
            channel = self.key_for("event", run_id)
            await self.client.publish(channel, message)
            await self.client.set(
                f"{channel}:last",
                message,
                ex=self.settings.redis_event_ttl_seconds,
            )
            return True
        except Exception as exc:
            self._record_error("publish_job_event", exc)
            return False

    @staticmethod
    def _parse_idempotency(value: str | bytes | None) -> IdempotencyRecord | None:
        if value is None:
            return None
        try:
            payload = json.loads(value)
            return IdempotencyRecord(
                run_id=str(payload["run_id"]),
                request_hash=str(payload["request_hash"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _rate_limit_failure(self, capacity: int, exc: Exception) -> RateLimitDecision:
        self._record_error("rate_limit", exc)
        return RateLimitDecision(
            allowed=self.settings.redis_fail_open,
            remaining=capacity if self.settings.redis_fail_open else 0,
            degraded=True,
            error_code="REDIS_UNAVAILABLE",
        )

    def _record_error(self, operation: str, exc: Exception) -> None:
        self.metrics["errors"] += 1
        log_event(
            logger,
            "redis_shared_state_unavailable",
            operation=operation,
            error_type=type(exc).__name__,
        )


def build_shared_state(settings: Settings):
    if not settings.redis_enabled:
        return NoopSharedState()
    return RedisSharedState.from_settings(settings)
