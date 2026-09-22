from __future__ import annotations

import hashlib
import time
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel, Field, model_validator

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import Evidence, SourceReference, ToolResult
from financial_research_agent.retrieval.web import (
    WebDocument,
    WebDocumentIndex,
    WebSearchProvider,
    WebSearchProviderError,
    WebSearchRequest,
)
from financial_research_agent.tools.base import FinancialTool, ToolDefinition


class WebSearchInput(BaseModel):
    stock_code: str = Field(pattern=r"^\d{6}$")
    query: str = Field(min_length=2, max_length=300)
    start_date: date | None = None
    end_date: date | None = None
    topic: str = Field(default="news", pattern=r"^(news|general)$")
    max_results: int = Field(default=8, ge=1, le=12)
    include_domains: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_dates(self) -> WebSearchInput:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("web search date range is invalid")
        return self


class WebSearchTool(FinancialTool):
    definition = ToolDefinition(
        name="web_search",
        version="1.0.0",
        description=(
            "Search public web/news sources for one stock through a controlled provider, "
            "index traceable documents, and return URL-grounded Evidence."
        ),
        timeout_seconds=90,
        max_rows=12,
        data_domain="public_web",
    )
    input_model = WebSearchInput

    def __init__(
        self,
        settings: Settings,
        provider: WebSearchProvider,
        index: WebDocumentIndex,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.index = index

    async def execute(self, task_id: str, arguments: WebSearchInput) -> ToolResult:
        return await self.execute_incremental(task_id, arguments, watermark=None)

    async def execute_incremental(
        self,
        task_id: str,
        arguments: WebSearchInput,
        *,
        watermark: datetime | None,
    ) -> ToolResult:
        started = time.perf_counter()
        configured_domains = set(self.settings.allowed_web_domains)
        requested_domains = {item.lower() for item in arguments.include_domains}
        if configured_domains and requested_domains - configured_domains:
            return self._failure(task_id, started, "WEB_DOMAIN_FORBIDDEN")
        domains = sorted(requested_domains or configured_domains)
        start_date = arguments.start_date
        if watermark is not None:
            incremental = (
                watermark - timedelta(hours=self.settings.web_search_overlap_hours)
            ).date()
            start_date = max(start_date, incremental) if start_date else incremental
        request = WebSearchRequest(
            query=arguments.query,
            stock_code=arguments.stock_code,
            start_date=start_date,
            end_date=arguments.end_date,
            topic=arguments.topic,
            max_results=min(arguments.max_results, self.settings.web_search_max_results),
            include_domains=domains,
        )
        try:
            documents = await self.provider.search(request)
            await self.index.initialize()
            changes = await self.index.upsert(documents)
            indexed = await self.index.search(request)
        except WebSearchProviderError as exc:
            return self._failure(task_id, started, exc.code)
        except Exception as exc:
            return self._failure(
                task_id, started, f"WEB_INDEX_UNAVAILABLE:{type(exc).__name__}"
            )
        if not indexed:
            return self._failure(task_id, started, "WEB_SEARCH_EMPTY")
        evidence = [self._evidence(arguments.stock_code, item, changes) for item in indexed]
        return ToolResult(
            task_id=task_id,
            success=True,
            evidence=evidence,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    @staticmethod
    def _failure(task_id: str, started: float, code: str) -> ToolResult:
        messages = {
            "WEB_SEARCH_NOT_CONFIGURED": "public web search provider is not configured",
            "WEB_SEARCH_RATE_LIMITED": "public web search provider rate limited the request",
            "WEB_SEARCH_TIMEOUT": "public web search provider timed out",
            "WEB_SEARCH_EMPTY": "public web search returned no traceable documents",
            "WEB_DOMAIN_FORBIDDEN": "requested domain is outside the configured allowlist",
        }
        return ToolResult(
            task_id=task_id,
            success=False,
            error_code=code,
            error_message=messages.get(code, "public web retrieval failed"),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    @staticmethod
    def _evidence(
        stock_code: str,
        document: WebDocument,
        changes: dict[str, int],
    ) -> Evidence:
        excerpt = document.content[:800].strip()
        evidence_id = "web-" + hashlib.sha256(
            f"{document.document_id}:{document.content_hash}".encode()
        ).hexdigest()[:16]
        published = document.published_at.isoformat() if document.published_at else "未知"
        return Evidence(
            evidence_id=evidence_id,
            evidence_type="web_source",
            subject=stock_code,
            statement=f"{document.title}；发布时间：{published}。{excerpt[:240]}",
            data={
                "title": document.title,
                "published_at": document.published_at,
                "fetched_at": document.fetched_at,
                "excerpt": excerpt,
                "provider": document.provider,
                "source_tier": document.source_tier,
                "content_hash": document.content_hash,
                "content_version": document.content_version,
                "index_changes": changes,
            },
            source=SourceReference(
                source_type="knowledge",
                locator=document.canonical_url,
                observed_at=datetime.now(timezone.utc),
                metadata={
                    "es_document_id": document.document_id,
                    "domain": document.domain,
                    "published_at": (
                        document.published_at.isoformat()
                        if document.published_at
                        else None
                    ),
                    "fetched_at": document.fetched_at.isoformat(),
                    "content_hash": document.content_hash,
                    "content_version": document.content_version,
                },
            ),
        )
