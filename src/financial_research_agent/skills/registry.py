from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Iterable

from financial_research_agent.domain.models import QuerySpec, ToolName
from financial_research_agent.skills.models import (
    EvidenceRequirement,
    SkillDefinition,
    ReportProfile,
    SkillSelection,
    SkillSnapshot,
    SkillStatus,
    SkillType,
    WorkflowConstraints,
)


class SkillConflict(ValueError):
    pass


class SkillRegistry:
    def __init__(self, definitions: Iterable[SkillDefinition]) -> None:
        self._versions: dict[str, SkillDefinition] = {}
        for definition in definitions:
            if definition.version_id in self._versions:
                raise ValueError(f"duplicate skill version: {definition.version_id}")
            self._versions[definition.version_id] = definition
        profile_path = Path(__file__).with_name("profiles.json")
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
        self._profiles = {
            item["id"]: ReportProfile.model_validate(item)
            for item in payload["profiles"]
        }

    @classmethod
    def from_builtin_catalog(cls) -> SkillRegistry:
        package_root = Path(__file__).with_name("packages")
        manifests = sorted(package_root.glob("*/manifest.yaml"))
        path = Path(__file__).with_name("catalog.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        definitions = [
            SkillDefinition.model_validate(item) for item in payload["skills"]
        ]
        definitions.extend(
            SkillDefinition.model_validate(
                json.loads(manifest.read_text(encoding="utf-8"))
            )
            for manifest in manifests
        )
        return cls(definitions)

    def versions(self) -> list[SkillDefinition]:
        return sorted(self._versions.values(), key=lambda item: item.version_id)

    def get(self, version_id: str, *, require_active: bool = True) -> SkillDefinition:
        try:
            definition = self._versions[version_id]
        except KeyError as exc:
            raise ValueError(f"unknown skill version: {version_id}") from exc
        if require_active and definition.status != SkillStatus.ACTIVE:
            raise ValueError(f"skill version is not ACTIVE: {version_id}")
        return definition

    def select(self, query: QuerySpec, available_tools: set[str]) -> SkillSelection:
        candidates = [
            item
            for item in self._versions.values()
            if item.status == SkillStatus.ACTIVE
            and item.skill_type != SkillType.REPORT
            and item.matches(query)
        ]
        if any(item.id == "comprehensive_stock_analysis" for item in candidates):
            candidates = [
                item
                for item in candidates
                if item.id != "comprehensive_stock_research"
            ]
        if not candidates:
            selection = SkillSelection(
                reason="default_flow:no_active_skill",
                effective_allowed_tools=[
                    ToolName(name) for name in sorted(available_tools)
                ],
            )
            selection = self._apply_report_requirements(selection, query)
            return selection.model_copy(
                update={"report_profiles": self._profiles_for(query)}
            )
        candidates.sort(
            key=lambda item: (
                item.skill_type.value,
                item.id,
                item.version,
            )
        )
        selection = self.compose(candidates, available_tools)
        if any(
            item.skill_id == "comprehensive_stock_analysis"
            for item in selection.snapshots
        ):
            # Comprehensive intent can represent any explicit combination of
            # market, financial and report domains. Its runtime Evidence gate
            # must follow the original question instead of a fixed superset.
            requirements: dict[str, int] = {}
            if "market" in query.analysis_domains:
                if "technical_analysis" in query.dimensions:
                    requirements["technical"] = 1
                else:
                    requirements.update({"market": 1, "indicator": 1})
            if "financial" in query.analysis_domains:
                requirements[
                    "fundamental"
                    if "fundamental_analysis" in query.dimensions
                    else "financial"
                ] = 1
            if "report" in query.analysis_domains:
                requirements["report_candidate"] = 1
                if query.report_request and query.report_request.mode == "deep":
                    requirements["research_report"] = 1
            if "event" in query.analysis_domains:
                requirements["web_source"] = 1
            if "factor" in query.analysis_domains:
                requirements["factor"] = 1
            selection = selection.model_copy(
                update={
                    "required_evidence": [
                        EvidenceRequirement(
                            evidence_type=name,
                            minimum_count=count,
                        )
                        for name, count in sorted(requirements.items())
                    ]
                }
            )
        selection = self._apply_report_requirements(selection, query)
        if query.intent.value == "event":
            effective = list(selection.effective_allowed_tools)
            if ToolName.WEB_SEARCH in effective:
                effective = [
                    item for item in effective if item != ToolName.EVENT_SEARCH
                ]
                requirement = "web_source"
            else:
                requirement = "event"
            selection = selection.model_copy(
                update={
                    "effective_allowed_tools": effective,
                    "required_evidence": [
                        EvidenceRequirement(
                            evidence_type=requirement, minimum_count=1
                        )
                    ],
                }
            )
        return selection.model_copy(
            update={"report_profiles": self._profiles_for(query)}
        )

    @staticmethod
    def _apply_report_requirements(
        selection: SkillSelection, query: QuerySpec
    ) -> SkillSelection:
        if "report" not in query.analysis_domains:
            return selection
        requirements = [
            item
            for item in selection.required_evidence
            if item.evidence_type not in {"report_candidate", "research_report"}
        ]
        requirements.append(
            EvidenceRequirement(evidence_type="report_candidate", minimum_count=1)
        )
        if query.report_request and query.report_request.mode == "deep":
            requirements.append(
                EvidenceRequirement(evidence_type="research_report", minimum_count=1)
            )
        return selection.model_copy(update={"required_evidence": requirements})

    def _profiles_for(self, query: QuerySpec) -> list[ReportProfile]:
        requested = [name for name in ("concise", "risk") if name in query.dimensions]
        return [self._profiles[name] for name in requested or ["standard"]]

    def compose(
        self,
        definitions: Iterable[SkillDefinition],
        available_tools: set[str],
    ) -> SkillSelection:
        selected = list(definitions)
        if not selected:
            raise ValueError("cannot compose an empty skill selection")
        ids = {item.id for item in selected}
        for item in selected:
            conflicts = ids.intersection(item.conflicts_with)
            if conflicts:
                raise SkillConflict(
                    f"SKILL_CONFLICT:{item.id}:{','.join(sorted(conflicts))}"
                )
        tool_sets = [{tool.value for tool in item.allowed_tools} for item in selected]
        effective = set.intersection(set(available_tools), *tool_sets)
        if not effective:
            raise SkillConflict("SKILL_TOOL_INTERSECTION_EMPTY")
        requirements: dict[str, int] = {}
        for item in selected:
            for requirement in item.required_evidence:
                requirements[requirement.evidence_type] = max(
                    requirements.get(requirement.evidence_type, 0),
                    requirement.minimum_count,
                )
        limits = [item.workflow_constraints for item in selected]
        constraints = WorkflowConstraints(
            max_tool_calls=min(item.max_tool_calls for item in limits),
            max_model_calls=min(item.max_model_calls for item in limits),
            max_parallel_tools=min(item.max_parallel_tools for item in limits),
            max_report_revisions=min(
                item.max_report_revisions for item in limits
            ),
            replan_limit=min(item.replan_limit for item in limits),
        )
        return SkillSelection(
            snapshots=[SkillSnapshot.from_definition(item) for item in selected],
            reason=f"active_match:{','.join(item.version_id for item in selected)}",
            effective_allowed_tools=[
                ToolName(name) for name in sorted(effective)
            ],
            required_evidence=[
                EvidenceRequirement(evidence_type=name, minimum_count=count)
                for name, count in sorted(requirements.items())
            ],
            workflow_constraints=constraints,
        )

    @staticmethod
    def validate_plan(
        selection: SkillSelection, tool_names: Iterable[str]
    ) -> None:
        if not selection.snapshots:
            return
        planned = list(tool_names)
        allowed = {
            item.value for item in selection.effective_allowed_tools
        }
        forbidden = sorted(set(planned) - allowed)
        if forbidden:
            raise ValueError(f"SKILL_TOOL_FORBIDDEN:{','.join(forbidden)}")
        if len(planned) > selection.workflow_constraints.max_tool_calls:
            raise ValueError("SKILL_TOOL_BUDGET_EXCEEDED")

    @staticmethod
    def validate_evidence(
        selection: SkillSelection, evidence_types: Iterable[str]
    ) -> list[str]:
        counts = Counter(evidence_types)
        return [
            (
                f"SKILL_EVIDENCE_MISSING:{item.evidence_type}:"
                f"required={item.minimum_count}:actual={counts[item.evidence_type]}"
            )
            for item in selection.required_evidence
            if counts[item.evidence_type] < item.minimum_count
        ]
