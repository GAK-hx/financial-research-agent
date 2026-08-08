from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import QuerySpec
from financial_research_agent.governance.models import PolicyDecision
from financial_research_agent.governance.store import GovernanceStore
from financial_research_agent.skills.models import SkillSelection
from financial_research_agent.tools.base import FinancialTool


class PolicyDenied(PermissionError):
    pass


class PolicyEngine:
    def __init__(self, settings: Settings, store: GovernanceStore) -> None:
        self.settings = settings
        self.store = store

    async def authorize_model(
        self,
        *,
        run_id: str,
        node_name: str,
        operation: str,
    ) -> PolicyDecision:
        allowed = operation in {
            "plan",
            "generate_report",
            "revise_report",
            "summarize_context",
        }
        configured = bool(
            self.settings.model_name
            and self.settings.model_api_key
            and self.settings.model_base_url
        )
        if not allowed:
            reason = "MODEL_OPERATION_FORBIDDEN"
        elif not configured:
            reason = "MODEL_NOT_CONFIGURED"
        else:
            reason = "POLICY_ALLOW"
        decision = await self.store.record_policy_decision(
            run_id=run_id,
            node_name=node_name,
            action="model",
            resource=self.settings.model_name or "unconfigured",
            allowed=allowed and configured,
            reason_code=reason,
            policy_version=self.settings.policy_version,
            context={
                "operation": operation,
                "provider": self.settings.model_provider,
                "model": self.settings.model_name,
            },
            details={
                "operation": operation,
                "provider": self.settings.model_provider,
            },
        )
        if not decision.allowed:
            raise PolicyDenied(reason)
        return decision

    async def authorize_tool(
        self,
        *,
        run_id: str,
        node_name: str,
        tool: FinancialTool,
        arguments: dict[str, Any],
        query: QuerySpec,
        selection: SkillSelection,
    ) -> tuple[PolicyDecision, BaseModel]:
        reason = "POLICY_ALLOW"
        validated: BaseModel | None = None
        try:
            if not tool.definition.read_only:
                raise PolicyDenied("TOOL_WRITE_FORBIDDEN")
            if tool.definition.data_domain == "simulation":
                raise PolicyDenied("SIMULATION_DOMAIN_FORBIDDEN")
            if selection.snapshots and tool.definition.name not in {
                item.value for item in selection.effective_allowed_tools
            }:
                raise PolicyDenied("SKILL_TOOL_FORBIDDEN")
            validated = tool.validate_input(arguments)
            stock_code = getattr(validated, "stock_code", None)
            if stock_code and stock_code not in query.stock_codes:
                raise PolicyDenied("TOOL_STOCK_OUTSIDE_QUERY")
            stock_codes = getattr(validated, "stock_codes", None)
            if stock_codes and not set(stock_codes).issubset(query.stock_codes):
                raise PolicyDenied("TOOL_STOCK_OUTSIDE_QUERY")
            self._validate_date_scope(validated, query)
            self._validate_row_scope(validated, tool)
        except PolicyDenied as exc:
            reason = str(exc)
        except Exception as exc:
            reason = f"TOOL_ARGUMENT_INVALID:{type(exc).__name__}"
        allowed = reason == "POLICY_ALLOW"
        decision = await self.store.record_policy_decision(
            run_id=run_id,
            node_name=node_name,
            action="tool",
            resource=tool.definition.name,
            allowed=allowed,
            reason_code=reason,
            policy_version=self.settings.policy_version,
            context={
                "tool": tool.definition.name,
                "version": tool.definition.version,
                "arguments": arguments,
                "query": query.model_dump(mode="json"),
                "skills": selection.selected_ids,
            },
            details={
                "tool_version": tool.definition.version,
                "data_domain": tool.definition.data_domain,
                "read_only": tool.definition.read_only,
            },
        )
        if not allowed or validated is None:
            raise PolicyDenied(reason)
        return decision, validated

    @staticmethod
    def _validate_date_scope(value: BaseModel, query: QuerySpec) -> None:
        start = getattr(value, "start_date", None)
        end = getattr(value, "end_date", None)
        if (
            isinstance(start, date)
            and query.start_date
            and start < query.start_date
        ):
            raise PolicyDenied("TOOL_DATE_OUTSIDE_QUERY")
        if isinstance(end, date) and query.end_date and end > query.end_date:
            raise PolicyDenied("TOOL_DATE_OUTSIDE_QUERY")

    @staticmethod
    def _validate_row_scope(value: BaseModel, tool: FinancialTool) -> None:
        configured = tool.definition.max_rows
        if configured is None:
            return
        requested = getattr(value, "max_rows", None)
        if requested is None:
            requested = getattr(value, "max_periods", None)
        if requested is None:
            requested = getattr(value, "top_k", None)
        if requested is None:
            requested = getattr(value, "max_events", None)
        if requested is not None and requested > configured:
            raise PolicyDenied("TOOL_ROW_LIMIT_EXCEEDED")
