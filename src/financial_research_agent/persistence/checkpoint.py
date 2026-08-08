from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from financial_research_agent.config import Settings


class CheckpointPayloadTooLarge(ValueError):
    pass


class BoundedSerializer:
    def __init__(self, inner: Any, max_bytes: int) -> None:
        self.inner = inner
        self.max_bytes = max_bytes

    def dumps_typed(self, obj: Any) -> tuple[str, bytes]:
        typed = self.inner.dumps_typed(obj)
        self._check(typed)
        return typed

    def loads_typed(self, data: tuple[str, bytes]) -> Any:
        self._check(data)
        return self.inner.loads_typed(data)

    def _check(self, data: tuple[str, bytes]) -> None:
        size = len(data[0].encode("utf-8")) + len(data[1])
        if size > self.max_bytes:
            raise CheckpointPayloadTooLarge(
                f"CHECKPOINT_PAYLOAD_TOO_LARGE:size={size}:limit={self.max_bytes}"
            )


def build_checkpoint_serializer(settings: Settings):
    from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    class BoundedJsonPlusSerializer(JsonPlusSerializer):
        def dumps_typed(self, obj: Any) -> tuple[str, bytes]:
            typed = super().dumps_typed(obj)
            BoundedSerializer(self, settings.max_checkpoint_bytes)._check(typed)
            return typed

        def loads_typed(self, data: tuple[str, bytes]) -> Any:
            BoundedSerializer(self, settings.max_checkpoint_bytes)._check(data)
            return super().loads_typed(data)

    base = BoundedJsonPlusSerializer(
        pickle_fallback=False,
        allowed_json_modules=(),
        allowed_msgpack_modules=[],
    )
    if settings.checkpoint_encryption_enabled:
        key = settings.checkpoint_aes_key.encode("utf-8")
        if len(key) not in (16, 24, 32):
            raise ValueError("CHECKPOINT_AES_KEY must contain 16, 24, or 32 bytes")
        return EncryptedSerializer.from_pycryptodome_aes(serde=base, key=key)
    return base


@asynccontextmanager
async def postgres_checkpointer(settings: Settings):
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    serializer = build_checkpoint_serializer(settings)
    async with AsyncPostgresSaver.from_conn_string(
        settings.checkpoint_database_url,
        serde=serializer,
    ) as checkpointer:
        await checkpointer.setup()
        yield checkpointer
