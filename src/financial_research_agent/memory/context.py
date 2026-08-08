from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from financial_research_agent.domain.models import Evidence, QuerySpec
from financial_research_agent.memory.models import (
    BuiltContext,
    ContextItemRef,
    ContextManifest,
    ContextPolicy,
    MemoryKind,
    MemoryRecord,
)
from financial_research_agent.persistence.models import (
    ContextManifestRecord,
    ContextSummaryRecord,
)
from financial_research_agent.skills.models import SkillSelection


SummaryCallable = Callable[
    [str, str, dict[str, Any]], Awaitable[dict[str, Any]]
]
MAX_INLINE_EVIDENCE_ROWS = 20


class ContextOverflow(ValueError):
    pass


class EvidenceProtectionError(ValueError):
    pass


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def estimate_tokens(value: Any) -> int:
    encoded = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode("utf-8")
    # UTF-8 bytes are deliberately conservative for mixed Chinese/JSON text.
    return max(1, (len(encoded) + 2) // 3)


def _compact_data(value: Any, *, key: str | None = None) -> Any:
    if key == "rows" and isinstance(value, list):
        if len(value) <= MAX_INLINE_EVIDENCE_ROWS:
            return [_compact_data(item) for item in value]
        return {
            "omitted_from_model_context": True,
            "row_count": len(value),
            "reason": "bulk_rows_available_via_source_locator",
        }
    if isinstance(value, dict):
        return {
            item_key: _compact_data(item, key=item_key)
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_compact_data(item) for item in value]
    return value


def evidence_context_item(
    item: Evidence, *, compact_bulk_rows: bool = True
) -> dict[str, Any]:
    return {
        "evidence_id": item.evidence_id,
        "type": item.evidence_type,
        "subject": item.subject,
        "statement": item.statement,
        "data": (
            _compact_data(item.data) if compact_bulk_rows else item.data
        ),
        "source": {
            "type": item.source.source_type,
            "locator": item.source.locator,
            "observed_at": item.source.observed_at.isoformat(),
            "metadata": item.source.metadata,
        },
    }


def _protected_projection(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    protected: list[dict[str, Any]] = []
    for item in items:
        source = item["source"]
        data = item.get("data") or {}
        protected.append(
            {
                "evidence_id": item["evidence_id"],
                "type": item["type"],
                "subject": item["subject"],
                "statement": item["statement"],
                "statement_numbers": re.findall(
                    r"[-+]?\d[\d,.]*(?:%|元|亿元|万元|倍|日|年)?",
                    item["statement"],
                ),
                "source_type": source["type"],
                "source_locator": source["locator"],
                "source_metadata": source.get("metadata") or {},
                "attribution": {
                    key: data.get(key)
                    for key in (
                        "institution",
                        "report_title",
                        "page_number",
                        "chunk_id",
                        "report_date",
                        "formula_version",
                        "snapshot_id",
                        "data_as_of",
                    )
                    if data.get(key) is not None
                },
            }
        )
    return protected


class EvidenceProtector:
    @staticmethod
    def hash(items: list[dict[str, Any]]) -> str:
        return canonical_hash(_protected_projection(items))

    @classmethod
    def validate(
        cls,
        original: list[dict[str, Any]],
        compressed: list[dict[str, Any]],
    ) -> str:
        original_hash = cls.hash(original)
        if original_hash != cls.hash(compressed):
            raise EvidenceProtectionError(
                "EVIDENCE_PROTECTED_FIELDS_CHANGED"
            )
        return original_hash


DEFAULT_CONTEXT_POLICIES = {
    "interpret": ContextPolicy(
        policy_id="interpret_context_v1",
        node_name="interpret",
        max_input_tokens=2_500,
        reserved_output_tokens=0,
        max_session_items=4,
        max_preference_items=0,
    ),
    "select_skill": ContextPolicy(
        policy_id="select_skill_context_v1",
        node_name="select_skill",
        max_input_tokens=4_000,
        reserved_output_tokens=0,
        max_session_items=0,
        max_preference_items=0,
    ),
    "plan": ContextPolicy(
        policy_id="plan_context_v1",
        node_name="plan",
        max_input_tokens=16_000,
        reserved_output_tokens=4_096,
        max_session_items=4,
        max_preference_items=4,
        max_episodic_items=4,
        max_knowledge_items=8,
    ),
    "generate_report": ContextPolicy(
        policy_id="report_context_v1",
        node_name="generate_report",
        max_input_tokens=32_000,
        reserved_output_tokens=8_192,
        max_session_items=0,
        max_preference_items=4,
        max_episodic_items=2,
        max_knowledge_items=12,
        overflow_action="reject",
    ),
    "revise_report": ContextPolicy(
        policy_id="revision_context_v1",
        node_name="revise_report",
        max_input_tokens=40_000,
        reserved_output_tokens=8_192,
        max_session_items=0,
        max_preference_items=4,
        max_episodic_items=2,
        max_knowledge_items=12,
        overflow_action="reject",
    ),
}


class ContextBuilder:
    def __init__(
        self,
        *,
        policy_version: str,
        policies: dict[str, ContextPolicy] | None = None,
        model_summary_enabled: bool = False,
        compression_enabled: bool = True,
        summarizer: SummaryCallable | None = None,
    ) -> None:
        self.policy_version = policy_version
        self.policies = policies or DEFAULT_CONTEXT_POLICIES
        self.model_summary_enabled = model_summary_enabled
        self.compression_enabled = compression_enabled
        self.summarizer = summarizer

    async def build_interpret(
        self,
        *,
        run_id: str,
        question: str,
        memory: list[MemoryRecord],
    ) -> BuiltContext:
        payload = {
            "question": question,
            "session_memory": self._memory_payload(
                memory, MemoryKind.SESSION, limit=4
            ),
        }
        return await self._finalize(
            run_id=run_id,
            node_name="interpret",
            payload=payload,
            skill_versions=[],
        )

    async def build_plan(
        self,
        *,
        run_id: str,
        question: str,
        query: QuerySpec,
        selection: SkillSelection,
        tool_schemas: list[dict[str, Any]],
        budget: dict[str, Any] | None,
        memory: list[MemoryRecord],
        knowledge: list[dict[str, Any]] | None = None,
    ) -> BuiltContext:
        policy = self.policies["plan"]
        payload = {
            "question": question,
            "query": query.model_dump(mode="json"),
            "selected_skills": selection.selected_ids,
            "skill_constraints": selection.workflow_constraints.model_dump(
                mode="json"
            ),
            "effective_allowed_tools": [
                item.value for item in selection.effective_allowed_tools
            ],
            "tool_schemas": tool_schemas,
            "budget": budget,
            "session_memory": self._memory_payload(
                memory,
                MemoryKind.SESSION,
                limit=policy.max_session_items,
            ),
            "preferences": self._memory_payload(
                memory,
                MemoryKind.PREFERENCE,
                limit=policy.max_preference_items,
            ),
            "episodic_memory": self._memory_payload(
                memory,
                MemoryKind.EPISODIC,
                limit=policy.max_episodic_items,
            ),
            "knowledge": (knowledge or [])[: policy.max_knowledge_items],
        }
        return await self._finalize(
            run_id=run_id,
            node_name="plan",
            payload=payload,
            skill_versions=selection.selected_ids,
        )

    async def build_selection(
        self,
        *,
        run_id: str,
        query: QuerySpec,
        candidate_skill_ids: list[str],
    ) -> BuiltContext:
        return await self._finalize(
            run_id=run_id,
            node_name="select_skill",
            payload={
                "query": query.model_dump(mode="json"),
                "candidate_skill_ids": candidate_skill_ids,
                "policy_version": self.policy_version,
            },
            skill_versions=[],
        )

    async def build_report(
        self,
        *,
        run_id: str,
        node_name: str,
        query: QuerySpec,
        evidence: list[Evidence],
        selection: SkillSelection,
        memory: list[MemoryRecord],
        draft: dict[str, Any] | None = None,
        validation_errors: list[str] | None = None,
        knowledge: list[dict[str, Any]] | None = None,
    ) -> BuiltContext:
        original = [
            evidence_context_item(item, compact_bulk_rows=False)
            for item in evidence
        ]
        compressed = [
            evidence_context_item(
                item, compact_bulk_rows=self.compression_enabled
            )
            for item in evidence
        ]
        evidence_hash = EvidenceProtector.validate(original, compressed)
        policy = self.policies[node_name]
        payload: dict[str, Any] = {
            "query": query.model_dump(mode="json"),
            "evidence": compressed,
            "preferences": self._memory_payload(
                memory,
                MemoryKind.PREFERENCE,
                limit=policy.max_preference_items,
            ),
            "episodic_memory": self._memory_payload(
                memory,
                MemoryKind.EPISODIC,
                limit=policy.max_episodic_items,
            ),
            "knowledge": (knowledge or [])[: policy.max_knowledge_items],
            "report_sections": [
                section
                for snapshot in selection.snapshots
                for section in snapshot.report_sections
            ],
            "report_profiles": [
                item.model_dump(mode="json") for item in selection.report_profiles
            ],
        }
        if draft is not None:
            payload["draft"] = draft
        if validation_errors:
            payload["validation_errors"] = validation_errors
        return await self._finalize(
            run_id=run_id,
            node_name=node_name,
            payload=payload,
            skill_versions=selection.selected_ids,
            evidence_hash=evidence_hash,
            token_estimate_before_override=estimate_tokens(
                {
                    **payload,
                    "evidence": original,
                }
            ),
        )

    async def _finalize(
        self,
        *,
        run_id: str,
        node_name: str,
        payload: dict[str, Any],
        skill_versions: list[str],
        evidence_hash: str | None = None,
        token_estimate_before_override: int | None = None,
    ) -> BuiltContext:
        policy = self.policies[node_name]
        before = token_estimate_before_override or estimate_tokens(payload)
        candidate = self._deduplicate_context(
            json.loads(json.dumps(payload, ensure_ascii=False))
        )
        included = self._item_refs(candidate)
        trimmed: list[ContextItemRef] = []
        warnings: list[str] = [
            f"OUTPUT_TOKENS_RESERVED:{policy.reserved_output_tokens}"
        ]
        after = estimate_tokens(candidate)
        input_limit = max(256, policy.max_input_tokens - policy.reserved_output_tokens)
        can_summarize_memory = (
            policy.allow_model_summary
            and self.model_summary_enabled
            and self.summarizer is not None
            and any(
                candidate.get(key)
                for key in ("session_memory", "preferences", "episodic_memory")
            )
        )
        if after > input_limit:
            candidate, trimmed = self._trim_non_evidence(
                candidate,
                included,
                policy,
                input_limit,
                trim_to_budget=not can_summarize_memory,
            )
            after = estimate_tokens(candidate)
        summary_id = None
        summary_depth = 0
        summary_input_hash = None
        summary_source_refs: list[ContextItemRef] = []
        if (
            after > input_limit
            and can_summarize_memory
        ):
            (
                candidate,
                summary_id,
                summary_input_hash,
                summary_source_refs,
            ) = await self._summarize_once(
                run_id, node_name, candidate
            )
            summary_depth = 1
            after = estimate_tokens(candidate)
            warnings.append("MODEL_SUMMARY_USED")
        if after > input_limit:
            candidate, final_trimmed = self._trim_non_evidence(
                candidate,
                self._item_refs(candidate),
                policy,
                input_limit,
                trim_to_budget=True,
            )
            trimmed.extend(final_trimmed)
            after = estimate_tokens(candidate)
        if after > input_limit:
            raise ContextOverflow(
                f"CONTEXT_BUDGET_EXCEEDED:{node_name}:"
                f"limit={input_limit}:actual={after}"
            )
        if evidence_hash is not None:
            actual_hash = EvidenceProtector.hash(candidate.get("evidence", []))
            if actual_hash != evidence_hash:
                raise EvidenceProtectionError(
                    "EVIDENCE_PROTECTED_FIELDS_CHANGED"
                )
        manifest = ContextManifest(
            manifest_id=uuid4().hex,
            run_id=run_id,
            node_name=node_name,
            context_policy_id=policy.policy_id,
            skill_versions=skill_versions,
            policy_version=self.policy_version,
            included=self._item_refs(candidate),
            trimmed=trimmed,
            token_estimate_before=before,
            token_estimate_after=after,
            compression_ratio=(after / before if before else 1.0),
            summary_id=summary_id,
            summary_depth=summary_depth,
            summary_input_hash=summary_input_hash,
            summary_source_refs=summary_source_refs,
            evidence_protection_hash=evidence_hash,
            evidence_protection_passed=True,
            warnings=warnings,
            built_at=datetime.now(timezone.utc),
        )
        return BuiltContext(payload=candidate, manifest=manifest)

    @staticmethod
    def _trim_non_evidence(
        payload: dict[str, Any],
        included: list[ContextItemRef],
        policy: ContextPolicy,
        input_limit: int,
        *,
        trim_to_budget: bool = True,
    ) -> tuple[dict[str, Any], list[ContextItemRef]]:
        trimmed: list[ContextItemRef] = []
        for key, limit in (
            ("session_memory", policy.max_session_items),
            ("preferences", policy.max_preference_items),
            ("episodic_memory", policy.max_episodic_items),
            ("knowledge", policy.max_knowledge_items),
        ):
            values = payload.get(key)
            if not isinstance(values, list) or len(values) <= limit:
                continue
            for item in values[limit:]:
                trimmed.append(
                    ContextItemRef(
                        item_type=key,
                        item_id=str(item.get("memory_id", "unknown")),
                        priority={
                            "session_memory": 20,
                            "preferences": 30,
                            "episodic_memory": 25,
                            "knowledge": 60,
                        }[key],
                        content_hash=canonical_hash(item),
                        source_locator=ContextBuilder._source_locator(item),
                        version=ContextBuilder._version(item),
                        selection_reason="trimmed_by_item_limit",
                        estimated_tokens=estimate_tokens(item),
                    )
                )
            payload[key] = values[:limit]
        if not trim_to_budget:
            return payload, trimmed
        for key in ("session_memory", "episodic_memory", "preferences", "knowledge"):
            values = payload.get(key)
            while (
                isinstance(values, list)
                and values
                and estimate_tokens(payload) > input_limit
            ):
                item = values.pop()
                item_id = "unknown"
                if isinstance(item, dict):
                    item_id = str(
                        item.get("event_id")
                        or item.get("memory_id")
                        or item.get("chunk_id")
                        or "unknown"
                    )
                trimmed.append(
                    ContextItemRef(
                        item_type=key,
                        item_id=item_id,
                        priority={
                            "session_memory": 20,
                            "preferences": 30,
                            "episodic_memory": 25,
                            "knowledge": 60,
                        }[key],
                        content_hash=canonical_hash(item),
                        source_locator=ContextBuilder._source_locator(item),
                        version=ContextBuilder._version(item),
                        selection_reason="trimmed_by_token_budget",
                        estimated_tokens=estimate_tokens(item),
                    )
                )
        return payload, trimmed

    async def _summarize_once(
        self,
        run_id: str,
        node_name: str,
        payload: dict[str, Any],
    ) -> tuple[
        dict[str, Any],
        str,
        str,
        list[ContextItemRef],
    ]:
        # Evidence is deliberately excluded from summarization.
        source = {
            key: value
            for key, value in payload.items()
            if key in {"session_memory", "preferences", "episodic_memory"}
        }
        summary = await self.summarizer(run_id, node_name, source)
        source_numbers = set(re.findall(r"\d[\d,.]*", json.dumps(source)))
        summary_numbers = set(re.findall(r"\d[\d,.]*", json.dumps(summary)))
        if not summary_numbers.issubset(source_numbers):
            raise EvidenceProtectionError(
                "CONTEXT_SUMMARY_INTRODUCED_NUMBER"
            )
        result = dict(payload)
        result.pop("session_memory", None)
        result.pop("preferences", None)
        result.pop("episodic_memory", None)
        result["memory_summary"] = summary
        refs = self._item_refs(source)
        return result, uuid4().hex, canonical_hash(source), refs

    @staticmethod
    def _memory_payload(
        memory: list[MemoryRecord], kind: MemoryKind, *, limit: int
    ) -> list[dict[str, Any]]:
        return [
            {
                "memory_id": item.memory_id,
                "key": item.key,
                "value": item.value,
                "version": item.version,
                "source_id": item.source.source_id,
            }
            for item in memory
            if item.kind == kind
        ][:limit]

    @staticmethod
    def _item_refs(payload: dict[str, Any]) -> list[ContextItemRef]:
        refs: list[ContextItemRef] = []
        priorities = {
            "question": 100,
            "query": 100,
            "evidence": 100,
            "validation_errors": 100,
            "draft": 90,
            "tool_schemas": 80,
            "selected_skills": 80,
            "budget": 70,
            "preferences": 30,
            "session_memory": 20,
            "episodic_memory": 25,
            "knowledge": 60,
        }
        for key, value in payload.items():
            if isinstance(value, list):
                for index, item in enumerate(value):
                    item_id = None
                    if isinstance(item, dict):
                        item_id = (
                            item.get("evidence_id")
                            or item.get("event_id")
                            or item.get("memory_id")
                            or item.get("chunk_id")
                        )
                    refs.append(
                        ContextItemRef(
                            item_type=key,
                            item_id=str(item_id or index),
                            priority=priorities.get(key, 50),
                            content_hash=canonical_hash(item),
                            source_locator=ContextBuilder._source_locator(item),
                            version=ContextBuilder._version(item),
                            estimated_tokens=estimate_tokens(item),
                        )
                    )
            else:
                refs.append(
                    ContextItemRef(
                        item_type=key,
                        item_id=key,
                        priority=priorities.get(key, 50),
                        content_hash=canonical_hash(value),
                        source_locator=ContextBuilder._source_locator(value),
                        version=ContextBuilder._version(value),
                        estimated_tokens=estimate_tokens(value),
                    )
                )
        return refs

    @staticmethod
    def _source_locator(value: Any) -> str | None:
        if not isinstance(value, dict):
            return None
        source = value.get("source")
        if isinstance(source, dict) and source.get("locator"):
            return str(source["locator"])
        return next(
            (
                str(value[key])
                for key in ("raw_locator", "source_url", "source_id")
                if value.get(key)
            ),
            None,
        )

    @staticmethod
    def _version(value: Any) -> str | None:
        if not isinstance(value, dict):
            return None
        for key in ("document_version", "extraction_version", "version"):
            if value.get(key) is not None:
                return str(value[key])
        return None

    @staticmethod
    def _deduplicate_context(payload: dict[str, Any]) -> dict[str, Any]:
        for key in (
            "session_memory",
            "preferences",
            "episodic_memory",
            "knowledge",
        ):
            values = payload.get(key)
            if not isinstance(values, list):
                continue
            seen: set[str] = set()
            unique: list[Any] = []
            for item in values:
                identity = canonical_hash(item)
                if identity in seen:
                    continue
                seen.add(identity)
                unique.append(item)
            payload[key] = unique
        return payload


class ContextStore:
    def __init__(
        self,
        sessions: async_sessionmaker,
        *,
        model_name: str = "unconfigured",
        prompt_version: str = "context_summary_v1",
    ) -> None:
        self.sessions = sessions
        self.model_name = model_name
        self.prompt_version = prompt_version

    async def persist(
        self,
        manifest: ContextManifest,
        payload: dict[str, Any] | None = None,
    ) -> None:
        values = {
            "id": manifest.manifest_id,
            "run_id": manifest.run_id,
            "node_name": manifest.node_name,
            "context_policy_id": manifest.context_policy_id,
            "skill_versions": manifest.skill_versions,
            "policy_version": manifest.policy_version,
            "token_estimator_version": manifest.token_estimator_version,
            "included": [
                item.model_dump(mode="json") for item in manifest.included
            ],
            "trimmed": [
                item.model_dump(mode="json") for item in manifest.trimmed
            ],
            "token_estimate_before": manifest.token_estimate_before,
            "token_estimate_after": manifest.token_estimate_after,
            "compression_ratio": manifest.compression_ratio,
            "summary_id": manifest.summary_id,
            "summary_depth": manifest.summary_depth,
            "evidence_protection_hash": manifest.evidence_protection_hash,
            "evidence_protection_passed": (
                manifest.evidence_protection_passed
            ),
            "warnings": manifest.warnings,
            "created_at": manifest.built_at,
        }
        async with self.sessions.begin() as session:
            inserted = await session.scalar(
                pg_insert(ContextManifestRecord)
                .values(**values)
                .on_conflict_do_nothing(
                    constraint="uq_context_manifest_run_node"
                )
                .returning(ContextManifestRecord.id)
            )
            if inserted is None:
                existing = await session.scalar(
                    select(ContextManifestRecord).where(
                        ContextManifestRecord.run_id == manifest.run_id,
                        ContextManifestRecord.node_name
                        == manifest.node_name,
                    )
                )
                if existing is None:
                    raise RuntimeError("CONTEXT_MANIFEST_WRITE_LOST")
                if (
                    existing.context_policy_id
                    != manifest.context_policy_id
                    or existing.evidence_protection_hash
                    != manifest.evidence_protection_hash
                ):
                    raise RuntimeError("CONTEXT_MANIFEST_CONFLICT")
            if (
                manifest.summary_id
                and manifest.summary_input_hash
                and payload
                and payload.get("memory_summary") is not None
            ):
                await session.execute(
                    pg_insert(ContextSummaryRecord)
                    .values(
                        id=manifest.summary_id,
                        run_id=manifest.run_id,
                        node_name=manifest.node_name,
                        input_hash=manifest.summary_input_hash,
                        source_refs=[
                            item.model_dump(mode="json")
                            for item in manifest.summary_source_refs
                        ],
                        model_name=self.model_name,
                        prompt_version=self.prompt_version,
                        summary=payload["memory_summary"],
                        validation_passed=True,
                        validation_errors=[],
                    )
                    .on_conflict_do_nothing()
                )
