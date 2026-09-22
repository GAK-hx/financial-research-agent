from financial_research_agent.tools.base import FinancialTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, FinancialTool] = {}

    def register(self, tool: FinancialTool) -> None:
        name = tool.definition.name
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        if not tool.definition.read_only:
            raise ValueError("step-one registry only accepts read-only tools")
        if tool.definition.data_domain == "simulation":
            raise ValueError("formal registry rejects simulation tools")
        self._tools[name] = tool

    def has(self, name: str) -> bool:
        return name in self._tools

    def get(self, name: str) -> FinancialTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ValueError(f"tool is not allowed: {name}") from exc

    def schemas(self) -> list[dict]:
        return [
            {
                "name": tool.definition.name,
                "description": tool.definition.description,
                "input_schema": tool.input_model.model_json_schema(),
                "version": tool.definition.version,
                "data_domain": tool.definition.data_domain,
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": tool.definition.data_domain == "public_web",
                },
            }
            for tool in self._tools.values()
        ]
