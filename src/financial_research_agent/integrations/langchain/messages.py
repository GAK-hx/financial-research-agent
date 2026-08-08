from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, message_to_dict


def human_message_dict(content: str) -> dict[str, Any]:
    return message_to_dict(HumanMessage(content=content))


def ai_message_dict(
    payload: dict[str, Any],
    *,
    phase: str,
    source: str | None = None,
) -> dict[str, Any]:
    metadata = {"phase": phase}
    if source is not None:
        metadata["source"] = source
    return message_to_dict(
        AIMessage(
            content=json.dumps(payload, ensure_ascii=False),
            response_metadata=metadata,
        )
    )
