from __future__ import annotations

import asyncio
import hashlib
import re
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, Field, model_validator

from financial_research_agent.config import Settings


TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "spm", "from", "source"}


def canonicalize_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("WEB_URL_INVALID")
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=False)
            if key.lower() not in TRACKING_QUERY_KEYS
            and not key.lower().startswith(TRACKING_QUERY_PREFIXES)
        )
    )
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


class WebSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    stock_code: str = Field(pattern=r"^\d{6}$")
    start_date: date | None = None
    end_date: date | None = None
    topic: Literal["news", "general"] = "news"
    max_results: int = Field(default=8, ge=1, le=12)
    include_domains: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_dates(self) -> WebSearchRequest:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("web search date range is invalid")
        return self


class WebDocument(BaseModel):
    document_id: str
    canonical_url: str
    url: str
    domain: str
    title: str = Field(default="", max_length=1000)
    content: str = Field(min_length=1)
    score: float | None = None
    stock_codes: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    language: str = "zh"
    source_tier: Literal["official", "exchange", "major_media", "other"] = "other"
    provider: str
    published_at: datetime | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    fetched_at: datetime
    content_hash: str
    content_version: int = Field(default=1, ge=1)
    is_current: bool = True


class WebSearchProviderError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class WebSearchProvider(ABC):
    name: str

    @abstractmethod
    async def search(self, request: WebSearchRequest) -> list[WebDocument]:
        raise NotImplementedError


class DisabledWebSearchProvider(WebSearchProvider):
    name = "disabled"

    async def search(self, request: WebSearchRequest) -> list[WebDocument]:
        del request
        raise WebSearchProviderError("WEB_SEARCH_NOT_CONFIGURED")


class TavilyWebSearchProvider(WebSearchProvider):
    name = "tavily"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.client = client

    async def search(self, request: WebSearchRequest) -> list[WebDocument]:
        if not self.settings.web_search_api_key:
            raise WebSearchProviderError("WEB_SEARCH_NOT_CONFIGURED")
        payload: dict[str, Any] = {
            "query": f"{request.stock_code} {request.query}",
            "topic": request.topic,
            "search_depth": "advanced",
            "max_results": request.max_results,
            "include_answer": False,
            "include_raw_content": "text",
        }
        if request.start_date:
            payload["start_date"] = request.start_date.isoformat()
        if request.end_date:
            payload["end_date"] = request.end_date.isoformat()
        if request.include_domains:
            payload["include_domains"] = request.include_domains
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(
            base_url=self.settings.web_search_base_url.rstrip("/"),
            timeout=self.settings.web_search_timeout_seconds,
        )
        try:
            for attempt in range(self.settings.web_search_max_retries + 1):
                try:
                    response = await client.post(
                        "/search",
                        headers={
                            "Authorization": f"Bearer {self.settings.web_search_api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    if response.status_code == 429:
                        raise WebSearchProviderError("WEB_SEARCH_RATE_LIMITED")
                    response.raise_for_status()
                    return self._documents(response.json(), request)
                except WebSearchProviderError:
                    if attempt >= self.settings.web_search_max_retries:
                        raise
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt >= self.settings.web_search_max_retries:
                        raise WebSearchProviderError("WEB_SEARCH_TIMEOUT") from None
                except httpx.HTTPStatusError:
                    raise WebSearchProviderError("WEB_SEARCH_PROVIDER_ERROR") from None
                await asyncio.sleep(min(20.0, 2.0 ** attempt))
        finally:
            if owns_client:
                await client.aclose()
        return []

    def _documents(
        self, payload: dict[str, Any], request: WebSearchRequest
    ) -> list[WebDocument]:
        now = datetime.now(timezone.utc)
        documents = []
        for item in payload.get("results") or []:
            try:
                canonical = canonicalize_url(str(item.get("url") or ""))
            except ValueError:
                continue
            content = str(item.get("raw_content") or item.get("content") or "").strip()
            if not content:
                continue
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            published = item.get("published_date")
            try:
                published_at = (
                    datetime.fromisoformat(str(published).replace("Z", "+00:00"))
                    if published
                    else None
                )
            except ValueError:
                published_at = None
            documents.append(
                WebDocument(
                    document_id=hashlib.sha256(canonical.encode()).hexdigest(),
                    canonical_url=canonical,
                    url=str(item.get("url")),
                    domain=urlsplit(canonical).netloc,
                    title=str(item.get("title") or ""),
                    content=content,
                    score=item.get("score"),
                    stock_codes=[request.stock_code],
                    topics=[request.topic],
                    source_tier=_source_tier(urlsplit(canonical).netloc),
                    provider=self.name,
                    published_at=published_at,
                    first_seen_at=now,
                    last_seen_at=now,
                    fetched_at=now,
                    content_hash=content_hash,
                )
            )
        return documents


def _source_tier(domain: str) -> Literal["official", "exchange", "major_media", "other"]:
    if domain.endswith((".gov.cn", ".org.cn")):
        return "official"
    if domain in {"www.sse.com.cn", "www.szse.cn", "www.bse.cn"}:
        return "exchange"
    if domain in {
        "www.cnstock.com",
        "www.stcn.com",
        "finance.sina.com.cn",
        "www.cs.com.cn",
    }:
        return "major_media"
    return "other"


WEB_DOCUMENT_MAPPING = {
    "dynamic": "strict",
    "properties": {
        "document_id": {"type": "keyword"},
        "canonical_url": {"type": "keyword", "ignore_above": 2048},
        "url": {"type": "keyword", "ignore_above": 2048},
        "domain": {"type": "keyword"},
        "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
        "content": {"type": "text"},
        "score": {"type": "float"},
        "stock_codes": {"type": "keyword"},
        "topics": {"type": "keyword"},
        "language": {"type": "keyword"},
        "source_tier": {"type": "keyword"},
        "provider": {"type": "keyword"},
        "published_at": {"type": "date"},
        "first_seen_at": {"type": "date"},
        "last_seen_at": {"type": "date"},
        "fetched_at": {"type": "date"},
        "content_hash": {"type": "keyword"},
        "content_version": {"type": "integer"},
        "is_current": {"type": "boolean"},
    },
}


class WebDocumentIndex(ABC):
    @abstractmethod
    async def initialize(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def upsert(self, documents: list[WebDocument]) -> dict[str, int]:
        raise NotImplementedError

    @abstractmethod
    async def search(self, request: WebSearchRequest) -> list[WebDocument]:
        raise NotImplementedError


class InMemoryWebDocumentIndex(WebDocumentIndex):
    def __init__(self) -> None:
        self.documents: dict[str, WebDocument] = {}

    async def initialize(self) -> None:
        return None

    async def upsert(self, documents: list[WebDocument]) -> dict[str, int]:
        counts = {"new": 0, "updated": 0, "unchanged": 0}
        for document in documents:
            existing = self.documents.get(document.document_id)
            if existing is None:
                counts["new"] += 1
            elif existing.content_hash == document.content_hash:
                counts["unchanged"] += 1
                document = document.model_copy(
                    update={
                        "first_seen_at": existing.first_seen_at,
                        "content_version": existing.content_version,
                        "stock_codes": sorted(
                            set(existing.stock_codes + document.stock_codes)
                        ),
                        "topics": sorted(set(existing.topics + document.topics)),
                    }
                )
            else:
                counts["updated"] += 1
                document = document.model_copy(
                    update={
                        "first_seen_at": existing.first_seen_at,
                        "content_version": existing.content_version + 1,
                        "stock_codes": sorted(
                            set(existing.stock_codes + document.stock_codes)
                        ),
                        "topics": sorted(set(existing.topics + document.topics)),
                    }
                )
            self.documents[document.document_id] = document
        return counts

    async def search(self, request: WebSearchRequest) -> list[WebDocument]:
        terms = set(re.findall(r"[\w\u4e00-\u9fff]+", request.query.lower()))
        ranked = []
        for document in self.documents.values():
            if request.stock_code not in document.stock_codes or not document.is_current:
                continue
            if request.include_domains and document.domain not in request.include_domains:
                continue
            if request.start_date and document.published_at:
                if document.published_at.date() < request.start_date:
                    continue
            if request.end_date and document.published_at:
                if document.published_at.date() > request.end_date:
                    continue
            body = f"{document.title} {document.content}".lower()
            score = sum(body.count(term) for term in terms) + float(document.score or 0)
            ranked.append((score, document))
        ranked.sort(key=lambda item: (item[0], item[1].fetched_at), reverse=True)
        return [item[1] for item in ranked[: request.max_results]]


class ElasticsearchWebDocumentIndex(WebDocumentIndex):
    def __init__(self, settings: Settings, client=None) -> None:
        self.settings = settings
        if client is None:
            try:
                from elasticsearch import AsyncElasticsearch
            except ModuleNotFoundError as exc:
                raise RuntimeError("ELASTICSEARCH_CLIENT_NOT_INSTALLED") from exc
            client = AsyncElasticsearch(
                settings.elasticsearch_url,
                request_timeout=settings.elasticsearch_request_timeout_seconds,
                retry_on_timeout=True,
                max_retries=3,
            )
        self.client = client

    async def initialize(self) -> None:
        index = self.settings.elasticsearch_index_name
        alias = self.settings.elasticsearch_index_alias
        if not await self.client.indices.exists(index=index):
            await self.client.indices.create(index=index, mappings=WEB_DOCUMENT_MAPPING)
        if not await self.client.indices.exists_alias(name=alias):
            await self.client.indices.put_alias(index=index, name=alias)

    async def upsert(self, documents: list[WebDocument]) -> dict[str, int]:
        counts = {"new": 0, "updated": 0, "unchanged": 0}
        for document in documents:
            existing = None
            try:
                existing = await self.client.get(
                    index=self.settings.elasticsearch_index_alias,
                    id=document.document_id,
                )
            except Exception as exc:
                if getattr(exc, "status_code", None) != 404:
                    raise
            if existing:
                source = existing["_source"]
                first_seen_at = source["first_seen_at"]
                if isinstance(first_seen_at, str):
                    first_seen_at = datetime.fromisoformat(
                        first_seen_at.replace("Z", "+00:00")
                    )
                if source.get("content_hash") == document.content_hash:
                    counts["unchanged"] += 1
                    document = document.model_copy(
                        update={
                            "first_seen_at": first_seen_at,
                            "content_version": source.get("content_version", 1),
                            "stock_codes": sorted(
                                set(source.get("stock_codes", []))
                                | set(document.stock_codes)
                            ),
                            "topics": sorted(
                                set(source.get("topics", []))
                                | set(document.topics)
                            ),
                        }
                    )
                else:
                    counts["updated"] += 1
                    document = document.model_copy(
                        update={
                            "first_seen_at": first_seen_at,
                            "content_version": source.get("content_version", 1) + 1,
                            "stock_codes": sorted(
                                set(source.get("stock_codes", []))
                                | set(document.stock_codes)
                            ),
                            "topics": sorted(
                                set(source.get("topics", []))
                                | set(document.topics)
                            ),
                        }
                    )
            else:
                counts["new"] += 1
            await self.client.index(
                index=self.settings.elasticsearch_index_alias,
                id=document.document_id,
                document=document.model_dump(mode="json"),
                refresh=False,
            )
        if documents:
            await self.client.indices.refresh(index=self.settings.elasticsearch_index_alias)
        return counts

    async def search(self, request: WebSearchRequest) -> list[WebDocument]:
        filters: list[dict[str, Any]] = [
            {"term": {"stock_codes": request.stock_code}},
            {"term": {"is_current": True}},
        ]
        if request.include_domains:
            filters.append({"terms": {"domain": request.include_domains}})
        date_range = {}
        if request.start_date:
            date_range["gte"] = request.start_date.isoformat()
        if request.end_date:
            date_range["lte"] = request.end_date.isoformat()
        if date_range:
            filters.append({"range": {"published_at": date_range}})
        response = await self.client.search(
            index=self.settings.elasticsearch_index_alias,
            size=request.max_results,
            query={
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": f"{request.stock_code} {request.query}",
                                "fields": ["title^3", "content"],
                            }
                        }
                    ],
                    "filter": filters,
                }
            },
        )
        return [
            WebDocument.model_validate(hit["_source"])
            for hit in response["hits"]["hits"]
        ]


def build_web_search_components(settings: Settings) -> tuple[WebSearchProvider, WebDocumentIndex]:
    provider: WebSearchProvider
    if settings.web_search_enabled and settings.web_search_provider == "tavily":
        provider = TavilyWebSearchProvider(settings)
    else:
        provider = DisabledWebSearchProvider()
    index: WebDocumentIndex
    if settings.elasticsearch_enabled:
        index = ElasticsearchWebDocumentIndex(settings)
    else:
        index = InMemoryWebDocumentIndex()
    return provider, index
