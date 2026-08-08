from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.tools import StructuredTool

from financial_research_agent.domain.models import ToolResult
from financial_research_agent.tools.base import FinancialTool

ToolExecutor = Callable[[dict[str, Any]], Awaitable[ToolResult]]


def build_governed_structured_tool(
    tool: FinancialTool,
    executor: ToolExecutor,
) -> StructuredTool:
    """Expose a FinancialTool through LangChain without bypassing governance.

    The injected executor is owned by ToolGateway. The adapter performs no direct
    data access and returns a compact model view plus the complete ToolResult as
    a ToolMessage artifact.
    """

    async def invoke(**arguments: Any) -> tuple[str, dict[str, Any]]:
        normalized = tool.input_model.model_validate(arguments).model_dump(mode="json")
        result = await executor(normalized)
        documents: list[dict[str, Any]] = []
        if tool.definition.data_domain == "research_report":
            from financial_research_agent.integrations.langchain.retrieval import (
                evidence_to_document,
            )

            documents = [
                evidence_to_document(item).model_dump(mode="json")
                for item in result.evidence
                if item.evidence_type == "research_report"
            ]
        content = json.dumps(
            {
                "task_id": result.task_id,
                "success": result.success,
                "evidence_count": len(result.evidence),
                "error_code": result.error_code,
            },
            ensure_ascii=False,
        )
        return content, {
            "tool_result": result.model_dump(mode="json"),
            "tool_version": tool.definition.version,
            "data_domain": tool.definition.data_domain,
            "documents": documents,
        }

    return StructuredTool.from_function(
        coroutine=invoke,
        name=tool.definition.name,
        description=tool.definition.description,
        args_schema=tool.input_model,
        infer_schema=False,
        response_format="content_and_artifact",
    )
