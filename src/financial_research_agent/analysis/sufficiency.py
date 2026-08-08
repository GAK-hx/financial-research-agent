from __future__ import annotations

from collections import Counter

from financial_research_agent.analysis.models import EvidenceSufficiency, MissingEvidence
from financial_research_agent.domain.models import AnalysisPlan, Evidence, ToolName
from financial_research_agent.skills.models import SkillSelection


class EvidenceSufficiencyChecker:
    """Deterministic gate; the model cannot invent its own replan scope."""

    def check(
        self,
        *,
        selection: SkillSelection,
        evidence: list[Evidence],
        original_plan: AnalysisPlan,
        replan_count: int,
    ) -> EvidenceSufficiency:
        counts = Counter(item.evidence_type for item in evidence)
        missing: list[MissingEvidence] = []
        for requirement in selection.required_evidence:
            actual = counts[requirement.evidence_type]
            if actual >= requirement.minimum_count:
                continue
            candidate, arguments = self._candidate(requirement.evidence_type, original_plan)
            missing.append(MissingEvidence(
                evidence_type=requirement.evidence_type,
                required=requirement.minimum_count,
                actual=actual,
                reason="required Evidence count was not reached after controlled Tool execution",
                candidate_tool=candidate.value if candidate else None,
                safe_arguments=arguments,
            ))
        if not missing:
            return EvidenceSufficiency(passed=True)
        limit = selection.workflow_constraints.replan_limit
        candidates_exist = all(item.candidate_tool for item in missing)
        allowed = replan_count < limit and candidates_exist
        reason = None
        if replan_count >= limit:
            reason = "EVIDENCE_INSUFFICIENT_REPLAN_LIMIT"
        elif not candidates_exist:
            reason = "EVIDENCE_INSUFFICIENT_NO_SAFE_SUPPLEMENT"
        return EvidenceSufficiency(
            passed=False,
            missing=missing,
            replan_allowed=allowed,
            termination_reason=reason,
        )

    @staticmethod
    def _candidate(
        evidence_type: str, original_plan: AnalysisPlan
    ) -> tuple[ToolName | None, dict]:
        by_tool = {item.tool_name: item for item in original_plan.tasks}
        if evidence_type == "event" and ToolName.EVENT_SEARCH in by_tool:
            task = by_tool[ToolName.EVENT_SEARCH]
            if task.arguments.get("query"):
                return ToolName.EVENT_SEARCH, {
                    **task.arguments,
                    "query": None,
                    "max_events": 12,
                }
        if evidence_type == "research_report" and ToolName.REPORT_SEARCH in by_tool:
            task = by_tool[ToolName.REPORT_SEARCH]
            if int(task.arguments.get("top_k", 5)) < 10:
                return ToolName.REPORT_SEARCH, {**task.arguments, "top_k": 10}
        return None, {}
