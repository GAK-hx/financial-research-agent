from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from pydantic import TypeAdapter

from financial_research_agent.risk.domain.models import RiskCategory, RiskMetricDefinition


class RiskMetricRegistry:
    def __init__(self, definitions: list[RiskMetricDefinition]) -> None:
        keys = [(item.code, item.version) for item in definitions]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate risk metric code and version")
        self._definitions = {(item.code, item.version): item for item in definitions}

    @classmethod
    def load_default(cls) -> RiskMetricRegistry:
        path = files("financial_research_agent.risk").joinpath("risk_metrics_v1.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(TypeAdapter(list[RiskMetricDefinition]).validate_python(payload))

    @classmethod
    def load(cls, path: str | Path) -> RiskMetricRegistry:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(TypeAdapter(list[RiskMetricDefinition]).validate_python(payload))

    def get(self, code: str, version: str = "v1") -> RiskMetricDefinition:
        try:
            return self._definitions[(code, version)]
        except KeyError as exc:
            raise KeyError(f"unknown risk metric: {code}@{version}") from exc

    def by_category(self, category: RiskCategory) -> list[RiskMetricDefinition]:
        return sorted(
            (item for item in self._definitions.values() if item.category == category),
            key=lambda item: item.code,
        )

    def all(self) -> list[RiskMetricDefinition]:
        return sorted(self._definitions.values(), key=lambda item: (item.category, item.code))
