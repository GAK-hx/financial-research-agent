from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

SENSITIVE_MARKERS = ("api_key", "authorization", "password", "secret", "token")
SAFE_NUMERIC_TELEMETRY_KEYS = {
    "tokens",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "model_context_window_tokens",
    "model_max_output_tokens",
}


def redact(value: Any, key: str = "") -> Any:
    if (
        key.lower() in SAFE_NUMERIC_TELEMETRY_KEYS
        and (value is None or isinstance(value, (int, float)))
    ):
        return value
    if any(marker in key.lower() for marker in SENSITIVE_MARKERS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {child_key: redact(child, child_key) for child_key, child in value.items()}
    if isinstance(value, list):
        return [redact(child) for child in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        fields = getattr(record, "event_fields", None)
        if fields:
            payload.update(redact(fields))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    if any(getattr(handler, "_financial_json", False) for handler in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._financial_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.info(event, extra={"event_fields": {"event": event, **redact(fields)}})
