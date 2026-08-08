from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from financial_research_agent.domain.models import ToolResult


class ToolDefinition(BaseModel):
    name: str
    version: str = "1.0.0"
    description: str
    read_only: bool = True
    allow_parallel: bool = True
    timeout_seconds: int = 15
    max_rows: int | None = None
    data_domain: str


class FinancialTool(ABC):
    definition: ToolDefinition
    input_model: type[BaseModel]

    def validate_input(self, arguments: dict[str, Any]) -> BaseModel:
        unknown = sorted(set(arguments) - set(self.input_model.model_fields))
        if unknown:
            raise ValueError(
                f"TOOL_ARGUMENT_UNKNOWN:{','.join(unknown)}"
            )
        return self.input_model.model_validate(arguments)

    @abstractmethod
    async def execute(self, task_id: str, arguments: BaseModel) -> ToolResult:
        raise NotImplementedError
