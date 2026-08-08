from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ProviderCapability(BaseModel):
    provider: str
    model_name: str
    context_window_tokens: int = Field(ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    supports_json_object: bool = True
    supports_tool_calls: bool = True
    reports_usage: bool = True
    reports_cache_usage: bool = True
    thinking_mode: Literal["disabled", "enabled", "omit"] = "disabled"


class ModelUsage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cache_hit_tokens: int = Field(default=0, ge=0)
    cache_miss_tokens: int = Field(default=0, ge=0)
    estimated: bool = False
    cost_microunits: int | None = Field(default=None, ge=0)


class ModelGatewayResponse(BaseModel):
    content: dict[str, Any]
    usage: ModelUsage
    provider_request_id: str | None = None
    message: dict[str, Any] | None = None


class PolicyDecision(BaseModel):
    decision_id: str
    allowed: bool
    reason_code: str
    policy_version: str
    action: Literal["model", "tool"]
    resource: str
    details: dict[str, Any] = Field(default_factory=dict)


class BudgetLimits(BaseModel):
    model_calls: int = Field(ge=0)
    model_attempts: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    tool_attempts: int = Field(ge=0)
    evidence: int = Field(ge=0)
    report_revisions: int = Field(ge=0)
    replan: int = Field(default=0, ge=0)
    tokens: int | None = Field(default=None, ge=1)
    cost_microunits: int | None = Field(default=None, ge=1)


class BudgetReservation(BaseModel):
    entry_id: str
    reservation_key: str
    resource: str
    amount: int
    status: Literal["reserved", "committed", "released"]
    execute: bool = True


class BudgetSnapshot(BaseModel):
    limits: BudgetLimits
    reserved: dict[str, int] = Field(default_factory=dict)
    committed: dict[str, int] = Field(default_factory=dict)
    open_reservations: int = Field(default=0, ge=0)


class CompletionResult(BaseModel):
    passed: bool
    errors: list[str] = Field(default_factory=list)
    policy_version: str
    budget: BudgetSnapshot | None = None
