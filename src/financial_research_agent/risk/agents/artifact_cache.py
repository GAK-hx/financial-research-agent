from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from financial_research_agent.domain.models import Evidence, SourceReference, ToolResult
from financial_research_agent.retrieval.models import (
    AnalysisArtifact,
    ArtifactVisibility,
    AtomicQueryKey,
    CacheDecision,
    PresentationEnvelope,
    RetrievalSnapshot,
    build_analysis_key,
    canonical_hash,
)
from financial_research_agent.risk.agents.agent_models import (
    EvaluationDecision,
    RiskAssessmentArtifact,
)


class RiskCacheResult(BaseModel):
    artifact: AnalysisArtifact
    decision: str
    data_snapshot_id: str
    analysis_work_shared: bool = False


class RiskUserReport(BaseModel):
    """User-scoped presentation stored with the tenant-scoped Job result."""

    presentation: PresentationEnvelope
    public_artifact_id: str
    requested_dimensions: list[str] = Field(default_factory=list)
    narrative: str


class RiskArtifactCache:
    """Bridge risk-domain artifacts onto the shared retrieval/analysis cache.

    Data snapshots and validated analysis are public and versioned. User wording stays in
    the Job result and is never written into the public AnalysisArtifact payload.
    """

    def __init__(
        self,
        coordinator: Any,
        *,
        model_id: str,
        skill_versions: list[str],
        prompt_version: str = "risk_report_v1",
        policy_version: str = "financial_risk_read_only_v1",
        ttl_seconds: int = 21_600,
    ) -> None:
        self.coordinator = coordinator
        self.model_id = model_id
        self.skill_versions = skill_versions
        self.prompt_version = prompt_version
        self.policy_version = policy_version
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _context_version(controlled_context: dict[str, Any]) -> str:
        relevant = {
            "point_in_time": controlled_context.get("point_in_time", {}),
            "risk_candidates": controlled_context.get("risk_candidates", []),
            "risk_features": controlled_context.get("risk_features", []),
        }
        return canonical_hash(relevant)

    async def _resolve_data_snapshot(
        self,
        *,
        run_id: str,
        subject_id: str,
        report_period: str,
        as_of_date: str,
        data_snapshot_id: str,
        controlled_context: dict[str, Any],
    ) -> RetrievalSnapshot:
        context_version = self._context_version(controlled_context)
        key = AtomicQueryKey(
            stock_code=subject_id if len(subject_id) == 6 and subject_id.isdigit() else None,
            domain="risk_lake_snapshot",
            topic=f"{subject_id}|{report_period}|{as_of_date}",
            provider_policy_version="risk_snapshot_v1",
            parameters={
                "data_snapshot_id": data_snapshot_id,
                "context_version": context_version,
            },
        )
        resolution = await self.coordinator.resolve(
            key, run_id=run_id, task_id=f"risk_snapshot_{subject_id}"
        )
        if resolution.decision == CacheDecision.FRESH and resolution.snapshot:
            return resolution.snapshot
        if resolution.decision == CacheDecision.INFLIGHT:
            snapshot = await self.coordinator.wait_for_snapshot(resolution)
            if snapshot is None:
                raise TimeoutError("risk data snapshot single-flight timed out")
            return snapshot

        observed_at = datetime.now(timezone.utc)
        result = ToolResult(
            task_id=f"risk_snapshot_{subject_id}",
            success=True,
            latency_ms=0,
            evidence=[
                Evidence(
                    evidence_id=f"risk-snapshot:{subject_id}:{report_period}:{context_version[:16]}",
                    evidence_type="financial",
                    subject=subject_id,
                    statement="Point-in-time risk data snapshot registered for shared analysis.",
                    data={
                        "report_period": report_period,
                        "as_of_date": as_of_date,
                        "data_snapshot_id": data_snapshot_id,
                        "context_version": context_version,
                    },
                    source=SourceReference(
                        source_type="iceberg",
                        locator=data_snapshot_id,
                        observed_at=observed_at,
                        metadata={"feature_scope": "risk_candidates_and_features"},
                    ),
                )
            ],
            metadata={"public_snapshot": True},
        )
        try:
            return await self.coordinator.complete(
                resolution,
                key,
                result,
                source_version=context_version,
                ttl_seconds=self.ttl_seconds,
            )
        except Exception:
            await self.coordinator.fail(resolution, "RISK_SNAPSHOT_REGISTRATION_FAILED")
            raise

    def _analysis_key(
        self,
        *,
        subject_id: str,
        report_period: str,
        snapshot: RetrievalSnapshot,
        analysis_scope: str,
    ) -> str:
        return build_analysis_key(
            analysis_type=f"risk_assessment:{analysis_scope}",
            subjects=[subject_id, report_period],
            snapshot_dependencies={snapshot.snapshot_id: snapshot.evidence_hash},
            skill_versions=self.skill_versions,
            model_id=self.model_id,
            prompt_version=self.prompt_version,
            policy_version=self.policy_version,
        )

    @staticmethod
    def _shareable(artifact: RiskAssessmentArtifact) -> bool:
        return artifact.evaluation.decision in {
            EvaluationDecision.ACCEPT,
            EvaluationDecision.ACCEPT_WITH_LIMITATIONS,
        }

    async def get_or_compute(
        self,
        *,
        run_id: str,
        subject_id: str,
        report_period: str,
        as_of_date: str,
        data_snapshot_id: str,
        controlled_context: dict[str, Any],
        compute: Callable[[], Awaitable[RiskAssessmentArtifact]],
        analysis_scope: str = "standard_v1",
    ) -> RiskCacheResult:
        snapshot = await self._resolve_data_snapshot(
            run_id=run_id,
            subject_id=subject_id,
            report_period=report_period,
            as_of_date=as_of_date,
            data_snapshot_id=data_snapshot_id,
            controlled_context=controlled_context,
        )
        analysis_key = self._analysis_key(
            subject_id=subject_id,
            report_period=report_period,
            snapshot=snapshot,
            analysis_scope=analysis_scope,
        )
        cached = await self.coordinator.get_analysis(analysis_key)
        if cached is not None:
            return RiskCacheResult(
                artifact=cached,
                decision="fresh",
                data_snapshot_id=snapshot.snapshot_id,
            )

        work_key = AtomicQueryKey(
            stock_code=subject_id if len(subject_id) == 6 and subject_id.isdigit() else None,
            domain="risk_analysis_work",
            topic=analysis_key,
            provider_policy_version=self.policy_version,
            parameters={"analysis_key": analysis_key},
        )
        resolution = await self.coordinator.resolve(
            work_key, run_id=run_id, task_id=f"risk_analysis_{subject_id}"
        )
        if resolution.decision == CacheDecision.INFLIGHT:
            completed = await self.coordinator.wait_for_snapshot(resolution)
            if completed is None:
                raise TimeoutError("risk analysis single-flight timed out")
            cached = await self.coordinator.get_analysis(analysis_key)
            if cached is None:
                raise RuntimeError("shared risk analysis completed without an artifact")
            return RiskCacheResult(
                artifact=cached,
                decision="inflight_join",
                data_snapshot_id=snapshot.snapshot_id,
                analysis_work_shared=True,
            )
        owns_analysis_work = resolution.decision != CacheDecision.FRESH
        if resolution.decision == CacheDecision.FRESH:
            cached = await self.coordinator.get_analysis(analysis_key)
            if cached is not None:
                return RiskCacheResult(
                    artifact=cached,
                    decision="fresh",
                    data_snapshot_id=snapshot.snapshot_id,
                    analysis_work_shared=True,
                )

        try:
            risk_artifact = await compute()
            if not self._shareable(risk_artifact):
                raise ValueError("only accepted risk assessments may enter the public cache")
            shared = AnalysisArtifact(
                artifact_id=uuid4().hex,
                analysis_key=analysis_key,
                analysis_type=f"risk_assessment:{analysis_scope}",
                subjects=[subject_id],
                snapshot_dependencies={snapshot.snapshot_id: snapshot.evidence_hash},
                skill_versions=self.skill_versions,
                model_id=self.model_id,
                prompt_version=self.prompt_version,
                policy_version=self.policy_version,
                payload={"risk_assessment": risk_artifact.model_dump(mode="json")},
                validated=True,
                visibility=ArtifactVisibility.PUBLIC,
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds),
            )
            await self.coordinator.put_analysis(shared)
            if owns_analysis_work:
                await self.coordinator.complete(
                    resolution,
                    work_key,
                    ToolResult(
                        task_id=f"risk_analysis_{subject_id}",
                        success=True,
                        latency_ms=0,
                        metadata={"artifact_id": shared.artifact_id},
                    ),
                    source_version=analysis_key,
                    ttl_seconds=self.ttl_seconds,
                )
            return RiskCacheResult(
                artifact=shared,
                decision="computed",
                data_snapshot_id=snapshot.snapshot_id,
            )
        except Exception:
            if owns_analysis_work:
                await self.coordinator.fail(resolution, "RISK_ANALYSIS_FAILED")
            raise

    @staticmethod
    def present(
        result: RiskCacheResult,
        *,
        run_id: str,
        tenant_id: str,
        user_id: str,
        session_id: str,
        requested_dimensions: list[str],
        narrative: str,
    ) -> RiskUserReport:
        return RiskUserReport(
            presentation=PresentationEnvelope(
                run_id=run_id,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                analysis_artifact_ids=[result.artifact.artifact_id],
                cache_decisions={"risk_analysis": CacheDecision.FRESH},
                refresh_performed=result.decision == "computed",
                lineage={
                    "retrieval_snapshots": [result.data_snapshot_id],
                    "analysis_artifacts": [result.artifact.artifact_id],
                },
            ),
            public_artifact_id=result.artifact.artifact_id,
            requested_dimensions=requested_dimensions,
            narrative=narrative,
        )
