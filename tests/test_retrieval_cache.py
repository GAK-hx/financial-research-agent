from __future__ import annotations

import asyncio
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import ToolResult
from financial_research_agent.orchestration.evidence_builder import EvidenceBuilder
from financial_research_agent.retrieval.coordinator import InMemoryRetrievalCoordinator
from financial_research_agent.retrieval.models import (
    AnalysisArtifact,
    ArtifactVisibility,
    AtomicQueryKey,
    CacheDecision,
    build_analysis_key,
)
from financial_research_agent.retrieval.web import (
    InMemoryWebDocumentIndex,
    WebDocument,
    WebSearchProvider,
    WebSearchRequest,
    canonicalize_url,
)
from financial_research_agent.tools.web_search import WebSearchInput, WebSearchTool


def web_document(
    stock_code: str,
    *,
    content: str = "公司发布经营进展公告",
    published_at: datetime | None = None,
) -> WebDocument:
    now = datetime.now(timezone.utc)
    return WebDocument(
        document_id=f"doc-{stock_code}",
        canonical_url=f"https://example.com/news/{stock_code}",
        url=f"https://example.com/news/{stock_code}?utm_source=test",
        domain="example.com",
        title=f"{stock_code}经营进展",
        content=content,
        stock_codes=[stock_code],
        topics=["news"],
        provider="fake",
        published_at=published_at or now - timedelta(hours=1),
        first_seen_at=now,
        last_seen_at=now,
        fetched_at=now,
        content_hash=__import__("hashlib").sha256(content.encode()).hexdigest(),
    )


class FakeWebProvider(WebSearchProvider):
    name = "fake"

    def __init__(self) -> None:
        self.requests: list[WebSearchRequest] = []

    async def search(self, request: WebSearchRequest) -> list[WebDocument]:
        self.requests.append(request)
        return [
            web_document(
                request.stock_code,
                published_at=datetime.combine(
                    request.end_date, datetime.min.time(), timezone.utc
                ),
            )
        ]


def test_url_canonicalization_removes_tracking_but_keeps_business_parameters():
    value = canonicalize_url(
        "HTTPS://Example.COM/a//b/?utm_source=x&id=42&gclid=secret#part"
    )
    assert value == "https://example.com/a/b?id=42"


@pytest.mark.asyncio
async def test_web_tool_indexes_versions_and_returns_traceable_evidence():
    settings = Settings(
        web_search_enabled=True,
        web_search_provider="tavily",
        web_search_max_retries=0,
    )
    provider = FakeWebProvider()
    index = InMemoryWebDocumentIndex()
    tool = WebSearchTool(settings, provider, index)
    arguments = WebSearchInput(
        stock_code="600519",
        query="贵州茅台近期风险与经营消息",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 15),
    )

    first = await tool.execute("web_600519", arguments)
    second = await tool.execute_incremental(
        "web_600519_refresh",
        arguments,
        watermark=datetime(2026, 8, 15, 8, tzinfo=timezone.utc),
    )

    assert first.success and second.success
    assert first.evidence[0].evidence_type == "web_source"
    assert first.evidence[0].source.locator == "https://example.com/news/600519"
    assert first.evidence[0].source.metadata["content_hash"]
    assert provider.requests[-1].start_date == date(2026, 8, 14)
    EvidenceBuilder().build("run", [first], 10)
    assert second.evidence[0].data["index_changes"]["unchanged"] == 1


@pytest.mark.asyncio
async def test_multi_user_overlap_single_flight_partial_refresh_and_private_isolation():
    settings = Settings(
        retrieval_join_timeout_seconds=2,
        retrieval_join_poll_seconds=0.05,
    )
    coordinator = InMemoryRetrievalCoordinator(settings)
    external_calls = Counter()

    async def execute(user: str, stock_code: str) -> CacheDecision:
        key = AtomicQueryKey(
            stock_code=stock_code,
            domain="public_web",
            topic="近期风险与经营消息",
        )
        resolution = await coordinator.resolve(
            key, run_id=user, task_id=f"web_{stock_code}"
        )
        if resolution.decision == CacheDecision.INFLIGHT:
            snapshot = await coordinator.wait_for_snapshot(resolution)
            assert snapshot is not None
            return resolution.decision
        if resolution.decision == CacheDecision.FRESH:
            return resolution.decision
        external_calls[stock_code] += 1
        await asyncio.sleep(0.01)
        await coordinator.complete(
            resolution,
            key,
            ToolResult(task_id=f"web_{stock_code}", success=True, latency_ms=1),
            source_version="fake-v1",
            ttl_seconds=3600,
        )
        return resolution.decision

    users = {
        "u1": ["600519", "300750", "601318", "000858", "600036"],
        "u2": ["600519", "300750", "000858", "002594", "601166"],
        "u3": ["600519", "002594", "601166", "600276", "000333"],
        "u4": ["300750", "601318", "600276", "000333", "600030"],
        "u5": ["600036", "000858", "002594", "600030", "601398"],
    }
    decisions = await asyncio.gather(
        *(execute(user, code) for user, codes in users.items() for code in codes)
    )

    unique = set().union(*map(set, users.values()))
    assert len(unique) == 11
    assert sum(external_calls.values()) == len(unique)
    assert decisions.count(CacheDecision.INFLIGHT) == 25 - len(unique)

    before = sum(external_calls.values())
    await asyncio.gather(
        *(execute("u6", code) for code in ["600519", "300750", "601398", "600104", "000001"])
    )
    assert sum(external_calls.values()) - before == 2

    expired_codes = ["600519", "300750", "601398"]
    for code in expired_codes:
        key = AtomicQueryKey(
            stock_code=code,
            domain="public_web",
            topic="近期风险与经营消息",
        )
        current = coordinator.snapshots[key.cache_key]
        coordinator.snapshots[key.cache_key] = current.model_copy(
            update={"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
        )
    before = sum(external_calls.values())
    stale = await asyncio.gather(*(execute("u7", code) for code in expired_codes))
    assert stale == [CacheDecision.STALE] * 3
    assert sum(external_calls.values()) - before == 3

    public_a = AtomicQueryKey(
        stock_code="600519", domain="public_web", topic="风险", tenant_id="a"
    )
    public_b = AtomicQueryKey(
        stock_code="600519", domain="public_web", topic="风险", tenant_id="b"
    )
    private_a = AtomicQueryKey(
        domain="private_upload",
        topic="私有文档",
        visibility=ArtifactVisibility.TENANT,
        tenant_id="a",
    )
    private_b = private_a.model_copy(update={"tenant_id": "b"})
    assert public_a.cache_key == public_b.cache_key
    assert private_a.cache_key != private_b.cache_key


@pytest.mark.asyncio
async def test_only_validated_analysis_is_reused_and_dependency_change_invalidates():
    coordinator = InMemoryRetrievalCoordinator()
    key = AtomicQueryKey(stock_code="600519", domain="public_web", topic="风险")
    resolution = await coordinator.resolve(key, run_id="u1", task_id="web")
    snapshot = await coordinator.complete(
        resolution,
        key,
        ToolResult(task_id="web", success=True, latency_ms=1),
        source_version="v1",
        ttl_seconds=3600,
    )
    analysis_key = build_analysis_key(
        analysis_type="risk_v1",
        subjects=["600519"],
        snapshot_dependencies={snapshot.snapshot_id: snapshot.evidence_hash},
        skill_versions=["event_impact@1.0.0"],
        model_id="deepseek-v4-flash",
        prompt_version="report_v4",
        policy_version="financial_read_only_v1",
    )
    artifact = AnalysisArtifact(
        artifact_id="artifact-1",
        analysis_key=analysis_key,
        analysis_type="risk_v1",
        subjects=["600519"],
        snapshot_dependencies={snapshot.snapshot_id: snapshot.evidence_hash},
        skill_versions=["event_impact@1.0.0"],
        model_id="deepseek-v4-flash",
        prompt_version="report_v4",
        policy_version="financial_read_only_v1",
        payload={"facts": []},
        validated=True,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    await coordinator.put_analysis(artifact)
    assert await coordinator.get_analysis(analysis_key) == artifact

    coordinator.snapshots[key.cache_key] = snapshot.model_copy(
        update={"evidence_hash": "f" * 64, "generation": 2}
    )
    assert await coordinator.get_analysis(analysis_key) is None

    invalid = artifact.model_copy(
        update={"artifact_id": "artifact-2", "analysis_key": "e" * 64, "validated": False}
    )
    with pytest.raises(ValueError, match="only validated"):
        await coordinator.put_analysis(invalid)
