from __future__ import annotations

from typing import Any

from financial_research_agent.skills.models import SkillSelection


def skill_agent_context(selection: SkillSelection) -> dict[str, Any]:
    """Map governed Skill selection to LangChain-visible agent context."""
    return {
        "selected_skill_versions": selection.selected_ids,
        "allowed_tool_names": [
            item.value for item in selection.effective_allowed_tools
        ],
        "required_evidence": [
            item.model_dump(mode="json")
            for item in selection.required_evidence
        ],
        "workflow_constraints": (
            selection.workflow_constraints.model_dump(mode="json")
        ),
        "report_profiles": [
            item.model_dump(mode="json") for item in selection.report_profiles
        ],
        "instruction": (
            "Use only allowed_tool_names. Respect workflow_constraints and "
            "produce the required evidence types before completing the report."
        ),
    }
