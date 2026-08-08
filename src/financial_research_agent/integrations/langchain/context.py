from __future__ import annotations

from typing import Any

from langchain_core.runnables import Runnable, RunnableLambda

from financial_research_agent.memory.context import ContextBuilder
from financial_research_agent.memory.models import BuiltContext


def context_builder_runnable(
    builder: ContextBuilder,
    method_name: str,
) -> Runnable[dict[str, Any], BuiltContext]:
    """Expose one governed ContextBuilder operation as a LangChain Runnable."""
    method = getattr(builder, method_name)

    async def build(arguments: dict[str, Any]) -> BuiltContext:
        return await method(**arguments)

    return RunnableLambda(build).with_config(
        {
            "run_name": f"context_builder.{method_name}",
            "tags": ["financial-agent", "context-engineering"],
            "metadata": {
                "component": "ContextBuilder",
                "method": method_name,
                "policy_version": builder.policy_version,
            },
        }
    )
