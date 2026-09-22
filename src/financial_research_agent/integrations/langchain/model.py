from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import AIMessage, message_to_dict
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from financial_research_agent.domain.models import (
    AnalysisPlan,
    QuerySpec,
    ResearchReport,
)
from financial_research_agent.governance.models import (
    ModelGatewayResponse,
    ModelUsage,
)
from financial_research_agent.providers.model import (
    AttemptObserver,
    OpenAICompatibleProvider,
    ProviderUnavailable,
    StructuredOutputError,
)


class ContextSummary(BaseModel):
    summary: str


def _recover_structured_output(
    raw_content: str, schema: type[BaseModel]
) -> BaseModel | None:
    """Recover a valid object from common JSON-mode formatting deviations.

    This is deliberately local and deterministic. A schema formatting error should not
    consume several identical model retries; transport and rate-limit failures still use
    the configured retry policy.
    """
    stripped = raw_content.strip()
    candidates = [stripped]
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1).strip())
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if 0 <= first_brace < last_brace:
        candidates.append(stripped[first_brace : last_brace + 1])

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            return schema.model_validate(json.loads(candidate))
        except (json.JSONDecodeError, ValueError, TypeError):
            continue
    return None


class LangChainModelProvider(OpenAICompatibleProvider):
    """LangChain Runnable provider behind the existing governed model boundary."""

    async def create_structured_response(
        self,
        *,
        instruction: str,
        input_payload: dict[str, Any],
        schema: type[BaseModel],
        max_tokens: int,
        operation: str,
        attempt_observer: AttemptObserver | None = None,
    ) -> ModelGatewayResponse:
        return await self._invoke_structured(
            instruction=instruction,
            payload=input_payload,
            schema=schema,
            max_tokens=max_tokens,
            operation=operation,
            attempt_observer=attempt_observer,
        )

    async def create_plan_response(
        self,
        question: str,
        query: QuerySpec,
        tool_schemas: list[dict],
        *,
        attempt_observer: AttemptObserver | None = None,
        planning_context: dict[str, Any] | None = None,
    ) -> ModelGatewayResponse:
        instruction = (
            "Return an AnalysisPlan. Copy query_spec exactly into query. Use only "
            "the supplied read-only tools and their declared arguments. Every task "
            "must contain task_id, tool_name, arguments and depends_on. Do not emit "
            "SQL or Python. Choose exactly the tools exposed in planning_context and "
            "respect each structured input schema. Legacy market analysis uses "
            "market_query followed by indicator_calculator; dedicated technical, "
            "fundamental, event, factor and comparison intents use their named tools. "
            "Follow query_spec.analysis_domains exactly; a comprehensive intent does "
            "not authorize an unrequested analysis domain."
        )
        payload = {
            "question": question,
            "query_spec": query.model_dump(mode="json"),
            "tools": tool_schemas,
            "planning_context": planning_context,
            "output_schema": AnalysisPlan.model_json_schema(),
            "structure_example": {
                "query": query.model_dump(mode="json"),
                "tasks": [
                    {
                        "task_id": "task_identifier",
                        "tool_name": "one_name_from_supplied_tools",
                        "arguments": {},
                        "depends_on": [],
                    }
                ],
                "expected_sections": [query.intent.value],
            },
        }
        return await self._invoke_structured(
            instruction=instruction,
            payload=payload,
            schema=AnalysisPlan,
            max_tokens=4096,
            operation="plan",
            attempt_observer=attempt_observer,
        )

    async def create_report_response(
        self,
        question: str,
        report_context: dict,
        draft: dict | None = None,
        validation_errors: list[str] | None = None,
        *,
        attempt_observer: AttemptObserver | None = None,
    ) -> ModelGatewayResponse:
        instruction = (
            "Return a ResearchReport grounded only in current-run evidence. Every "
            "claim must cite supplied evidence_ids. Claims citing research reports "
            "must name the exact institution. Every number must occur in the same "
            "evidence item cited by that claim. The summary must provide "
            "summary_evidence_ids, and every summary number must occur in its cited "
            "evidence. Preserve negative directions; drawdown may be written as a "
            "positive magnitude. Split claims that combine numbers from different "
            "chunks. Do not invent facts or calculations. Risks must be structured "
            "objects with classification and evidence_ids; limitations must be "
            "structured objects with category and evidence_ids. When the selected Skill "
            "requests them, include an evidence-cited four-part risk_vector and "
            "optimistic/base/stress scenarios. Follow report_profiles without weakening "
            "citations. Include the research-only disclaimer."
        )
        payload = {
            "question": question,
            "report_context": report_context,
            "draft": draft,
            "validation_errors": validation_errors or [],
            "output_schema": ResearchReport.model_json_schema(),
            "structure_example": {
                "subjects": report_context["query"]["stock_codes"],
                "summary": "A concise evidence-based summary.",
                "summary_evidence_ids": [
                    "copy_an_exact_evidence_id_from_report_context"
                ],
                "claims": [
                    {
                        "claim": "A claim supported by current-run evidence.",
                        "evidence_ids": [
                            "copy_an_exact_evidence_id_from_report_context"
                        ],
                        "confidence": "medium",
                    }
                ],
                "risks": [
                    {
                        "risk": "At least one evidence-aware risk.",
                        "classification": "model_interpretation",
                        "evidence_ids": [
                            "copy_an_exact_evidence_id_from_report_context"
                        ],
                        "confidence": "medium",
                    }
                ],
                "limitations": [
                    {
                        "limitation": "State material data and scope limitations.",
                        "category": "scope",
                        "evidence_ids": [],
                    }
                ],
                "risk_vector": [
                    {"dimension": "technical", "level": "unknown", "rationale": "No technical Evidence when absent.", "evidence_ids": []},
                    {"dimension": "fundamental", "level": "unknown", "rationale": "No fundamental Evidence when absent.", "evidence_ids": []},
                    {"dimension": "event", "level": "unknown", "rationale": "No event Evidence when absent.", "evidence_ids": []},
                    {"dimension": "data_confidence", "level": "medium", "rationale": "Explain source coverage without unsupported numbers.", "evidence_ids": ["copy_an_exact_evidence_id_from_report_context"]}
                ],
                "scenarios": [
                    {"name": "optimistic", "assumptions": ["Evidence-grounded assumption"], "implication": "Conditional implication, not a forecast.", "evidence_ids": ["copy_an_exact_evidence_id_from_report_context"]},
                    {"name": "base", "assumptions": ["Evidence-grounded assumption"], "implication": "Conditional implication, not a forecast.", "evidence_ids": ["copy_an_exact_evidence_id_from_report_context"]},
                    {"name": "stress", "assumptions": ["Evidence-grounded assumption"], "implication": "Conditional implication, not a forecast.", "evidence_ids": ["copy_an_exact_evidence_id_from_report_context"]}
                ],
                "data_as_of": "YYYY-MM-DD or null",
                "disclaimer": "仅供研究参考，不构成投资建议。",
            },
        }
        return await self._invoke_structured(
            instruction=instruction,
            payload=payload,
            schema=ResearchReport,
            max_tokens=8192,
            operation=("revise_report" if draft is not None else "generate_report"),
            attempt_observer=attempt_observer,
        )

    async def create_context_summary_response(
        self,
        context: dict[str, Any],
        *,
        attempt_observer: AttemptObserver | None = None,
    ) -> ModelGatewayResponse:
        instruction = (
            "Summarize only the supplied session and preference context. Do not add "
            "facts, numbers, entities, credentials, investment conclusions, evidence "
            "or source locators."
        )
        return await self._invoke_structured(
            instruction=instruction,
            payload={"context": context},
            schema=ContextSummary,
            max_tokens=1024,
            operation="summarize_context",
            attempt_observer=attempt_observer,
        )

    async def _invoke_structured(
        self,
        *,
        instruction: str,
        payload: dict[str, Any],
        schema: type[BaseModel],
        max_tokens: int,
        operation: str,
        attempt_observer: AttemptObserver | None,
    ) -> ModelGatewayResponse:
        self._ensure_configured()
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    (
                        f"{instruction} Return only one valid JSON object "
                        "matching the requested structured schema."
                    ),
                ),
                ("human", "{payload}"),
            ]
        )
        model = self._chat_model(max_tokens=max_tokens)
        runnable = prompt | model.with_structured_output(
            schema,
            method="json_mode",
            include_raw=True,
        )
        prompt_payload = dict(payload)
        prompt_payload.setdefault("output_schema", schema.model_json_schema())
        serialized_payload = json.dumps(prompt_payload, ensure_ascii=False)
        last_parsing_error: Exception | None = None
        parsed_output: BaseModel | dict[str, Any] | None = None
        raw: Any = None
        for attempt in range(self.settings.model_max_retries + 1):
            observer_token = (
                await attempt_observer.before_attempt(attempt)
                if attempt_observer is not None
                else None
            )
            try:
                async with self.capacity.slot():
                    result = await runnable.ainvoke(
                        {"payload": serialized_payload},
                        config={
                            "tags": ["financial-agent", operation],
                            "metadata": {
                                "framework": "langchain",
                                "operation": operation,
                                "model": self.settings.model_name,
                                "prompt_version": self._prompt_version(operation),
                            },
                        },
                    )
                raw = result.get("raw")
                parsed = result.get("parsed")
                parsing_error = result.get("parsing_error")
                if parsing_error is not None or parsed is None:
                    raw_content = getattr(raw, "content", "")
                    if not isinstance(raw_content, str):
                        raw_content = json.dumps(
                            raw_content, ensure_ascii=False, default=str
                        )
                    recovered = _recover_structured_output(raw_content, schema)
                    if recovered is not None:
                        parsed_output = recovered
                        if attempt_observer is not None:
                            await attempt_observer.after_attempt(
                                observer_token, succeeded=True
                            )
                        break
                    last_parsing_error = (
                        parsing_error
                        if isinstance(parsing_error, Exception)
                        else ProviderUnavailable(
                            "model returned empty structured output"
                        )
                    )
                    if attempt_observer is not None:
                        await attempt_observer.after_attempt(
                            observer_token, succeeded=False
                        )
                    # Retrying the same valid HTTP response does not repair its JSON.
                    # Persist the raw output so the caller can inspect or selectively rerun it.
                    break
                if attempt_observer is not None:
                    await attempt_observer.after_attempt(observer_token, succeeded=True)
                parsed_output = parsed
                break
            except Exception as exc:
                if attempt_observer is not None:
                    await attempt_observer.after_attempt(observer_token, succeeded=False)
                if attempt >= self.settings.model_max_retries or not self._retryable(exc):
                    raise
                await self._retry_delay(attempt, exc)
        if parsed_output is None and last_parsing_error is not None:
            raw_content = getattr(raw, "content", "")
            if not isinstance(raw_content, str):
                raw_content = json.dumps(raw_content, ensure_ascii=False, default=str)
            raise StructuredOutputError(
                "structured output validation failed: "
                f"{type(last_parsing_error).__name__}",
                raw_output=raw_content[:20_000],
            )
        if parsed_output is None:
            raise ProviderUnavailable("model returned empty structured output")
        content = (
            parsed_output.model_dump(mode="json")
            if isinstance(parsed_output, BaseModel)
            else dict(parsed_output)
        )
        return ModelGatewayResponse(
            content=content,
            usage=self._message_usage(
                raw,
                payload=payload,
                content=content,
            ),
            provider_request_id=(
                getattr(raw, "id", None) or getattr(raw, "response_metadata", {}).get("id")
            ),
            message=(message_to_dict(raw) if isinstance(raw, AIMessage) else None),
        )

    def _chat_model(self, *, max_tokens: int) -> ChatOpenAI:
        extra_body: dict[str, Any] = {"max_tokens": max_tokens}
        if self.settings.model_thinking_mode != "omit":
            extra_body["thinking"] = {"type": self.settings.model_thinking_mode}
        if self.settings.model_thinking_mode == "enabled":
            extra_body["reasoning_effort"] = self.settings.model_reasoning_effort
        return ChatOpenAI(
            model=self.settings.model_name,
            api_key=self.settings.model_api_key,
            base_url=self.settings.model_base_url,
            timeout=self.settings.model_timeout_seconds,
            max_retries=0,
            temperature=(None if self.settings.model_thinking_mode == "enabled" else 0),
            extra_body=extra_body,
        )

    def _message_usage(
        self,
        message: Any,
        *,
        payload: dict[str, Any],
        content: dict[str, Any],
    ) -> ModelUsage:
        usage = getattr(message, "usage_metadata", None) or {}
        metadata = getattr(message, "response_metadata", None) or {}
        token_usage = metadata.get("token_usage") or {}
        input_tokens = int(usage.get("input_tokens") or token_usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or token_usage.get("completion_tokens") or 0)
        total_tokens = int(
            usage.get("total_tokens")
            or token_usage.get("total_tokens")
            or input_tokens + output_tokens
        )
        input_details = usage.get("input_token_details") or {}
        cache_hit = int(
            input_details.get("cache_read") or token_usage.get("prompt_cache_hit_tokens") or 0
        )
        cache_miss = int(
            token_usage.get("prompt_cache_miss_tokens") or max(0, input_tokens - cache_hit)
        )
        if not total_tokens:
            return self._usage(
                None,
                payload=payload,
                content=json.dumps(content, ensure_ascii=False),
            )
        cost = self._cost_microunits(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_hit_tokens=cache_hit,
            cache_miss_tokens=cache_miss,
        )
        return ModelUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cache_hit_tokens=cache_hit,
            cache_miss_tokens=cache_miss,
            estimated=False,
            cost_microunits=cost,
        )

    def _prompt_version(self, operation: str) -> str:
        if operation == "plan":
            return self.settings.planner_prompt_version
        if operation == "summarize_context":
            return self.settings.context_summary_prompt_version
        return self.settings.report_prompt_version

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code in {408, 409, 425, 429, 500, 502, 503, 504}:
            return True
        return type(exc).__name__ in {
            "APIConnectionError",
            "APITimeoutError",
            "ConnectError",
            "ReadError",
            "RemoteProtocolError",
            "TimeoutException",
        }
