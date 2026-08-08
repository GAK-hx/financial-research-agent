from __future__ import annotations

from typing import Any

from financial_research_agent.governance.models import (
    CompletionResult,
)
from financial_research_agent.governance.store import BudgetConflict, GovernanceStore
from financial_research_agent.orchestration.context import RunStage


class CompletionChecker:
    def __init__(
        self, store: GovernanceStore, *, policy_version: str
    ) -> None:
        self.store = store
        self.policy_version = policy_version

    async def check(self, state: dict[str, Any]) -> CompletionResult:
        errors: list[str] = []
        orchestration_completed = (
            state.get("orchestration_stage") == RunStage.COMPLETED.value
        )
        reporting_completed = state.get("reporting_status") == "completed"
        validation = state.get("validation") or {}
        if orchestration_completed and not state.get("evidence"):
            errors.append("COMPLETION_EVIDENCE_MISSING")
        if orchestration_completed and not reporting_completed:
            errors.append("COMPLETION_REPORT_NOT_COMPLETED")
        if reporting_completed and not validation.get("passed"):
            errors.append("COMPLETION_VALIDATION_NOT_PASSED")
        manifests = state.get("context_manifests") or {}
        if orchestration_completed:
            for node_name in ("plan", "generate_report"):
                manifest = manifests.get(node_name)
                if not manifest:
                    errors.append(
                        f"COMPLETION_CONTEXT_MANIFEST_MISSING:{node_name}"
                    )
                    continue
                if not manifest.get("evidence_protection_passed", True):
                    errors.append(
                        f"COMPLETION_EVIDENCE_PROTECTION_FAILED:{node_name}"
                    )
        try:
            budget = await self.store.snapshot(state["run_id"])
        except BudgetConflict:
            budget = None
        if budget is not None and budget.open_reservations:
            errors.append(
                f"COMPLETION_BUDGET_RESERVATIONS_OPEN:{budget.open_reservations}"
            )
        # A controlled failed run is a valid terminal state. Passing here means
        # its terminal classification is internally consistent, not that the
        # research request succeeded.
        if not orchestration_completed and reporting_completed:
            errors.append("COMPLETION_CONFLICTING_TERMINAL_STATE")
        return CompletionResult(
            passed=not errors,
            errors=errors,
            policy_version=self.policy_version,
            budget=budget,
        )
