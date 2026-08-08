from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from financial_research_agent.analysis.models import FactorDefinition


@dataclass(frozen=True)
class UniverseDefinition:
    universe_id: str
    version: str
    effective_date: date
    selection_policy: str
    members: tuple[str, ...]


class FactorRegistry:
    def __init__(self, version: str, factors: list[FactorDefinition]) -> None:
        self.version = version
        self._factors = {item.name: item for item in factors}
        if len(self._factors) != len(factors):
            raise ValueError("duplicate factor definition")

    @classmethod
    def builtin(cls) -> FactorRegistry:
        payload = json.loads(
            Path(__file__).with_name("factor_registry.json").read_text(encoding="utf-8")
        )
        return cls(
            payload["registry_version"],
            [FactorDefinition.model_validate(item) for item in payload["factors"]],
        )

    def get(self, name: str) -> FactorDefinition:
        try:
            return self._factors[name]
        except KeyError as exc:
            raise ValueError(f"unknown factor: {name}") from exc

    def all(self) -> list[FactorDefinition]:
        return list(self._factors.values())


class UniverseRegistry:
    def __init__(self, universes: list[UniverseDefinition]) -> None:
        self._universes = {item.universe_id: item for item in universes}

    @classmethod
    def builtin(cls) -> UniverseRegistry:
        payload = json.loads(
            Path(__file__).with_name("universes.json").read_text(encoding="utf-8")
        )
        return cls(
            [
                UniverseDefinition(
                    universe_id=item["universe_id"],
                    version=item["version"],
                    effective_date=date.fromisoformat(item["effective_date"]),
                    selection_policy=item["selection_policy"],
                    members=tuple(item["members"]),
                )
                for item in payload["universes"]
            ]
        )

    def get(self, universe_id: str) -> UniverseDefinition:
        try:
            return self._universes[universe_id]
        except KeyError as exc:
            raise ValueError(f"unknown universe: {universe_id}") from exc
