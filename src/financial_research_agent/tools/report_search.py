from __future__ import annotations

import hashlib
import time
from datetime import UTC, date, datetime
from typing import Protocol

import numpy as np
from pydantic import BaseModel, Field

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import Evidence, SourceReference, ToolResult
from financial_research_agent.rag.embedding import BgeEmbeddingModel
from financial_research_agent.rag.models import RetrievalHit
from financial_research_agent.rag.store import COLLECTION_NAME, HybridReportStore
from financial_research_agent.tools.base import FinancialTool, ToolDefinition


class QueryEmbedder(Protocol):
    def encode(self, texts: list[str]) -> np.ndarray: ...


class ReportStore(Protocol):
    def prepare(self, dimension: int, mode: str = "skip"): ...
    def search(
        self,
        query_vector: np.ndarray,
        stock_code: str,
        top_k: int,
        *,
        query_text: str | None = None,
        filters: dict | None = None,
    ) -> list[RetrievalHit]: ...


class ReportSearchInput(BaseModel):
    stock_code: str = Field(pattern=r"^\d{6}$")
    query: str = Field(min_length=2, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)
    start_date: date | None = None
    end_date: date | None = None
    institution: str | None = Field(default=None, min_length=2, max_length=128)


class ReportSearchTool(FinancialTool):
    definition = ToolDefinition(
        name="report_search",
        version="1.0.0",
        description="Search page-addressable research report evidence for one allowed stock.",
        timeout_seconds=30,
        max_rows=10,
        data_domain="research_report",
    )
    input_model = ReportSearchInput

    def __init__(
        self,
        settings: Settings,
        embedder: QueryEmbedder | None = None,
        store: ReportStore | None = None,
    ) -> None:
        self.settings = settings
        self.embedder = embedder or BgeEmbeddingModel(settings.rag_embedding_model)
        self.store = store or HybridReportStore(settings)
        self._prepared = False

    async def execute(self, task_id: str, arguments: ReportSearchInput) -> ToolResult:
        started = time.perf_counter()
        if arguments.stock_code not in self.settings.stock_codes:
            return self._error(task_id, started, "STOCK_NOT_ALLOWED", "stock is outside configured pool")
        try:
            if self.settings.agent_framework == "langchain":
                from financial_research_agent.integrations.langchain.retrieval import (
                    LangChainReportRetriever,
                    document_to_evidence,
                )

                retriever = LangChainReportRetriever(
                    stock_code=arguments.stock_code,
                    top_k=arguments.top_k,
                    embedder=self.embedder,
                    store=self.store,
                    filters={
                        "start_date": arguments.start_date,
                        "end_date": arguments.end_date,
                        "institution": arguments.institution,
                    },
                )
                documents = await retriever.ainvoke(
                    arguments.query,
                    config={
                        "run_name": "report_search.retrieve",
                        "tags": ["financial-agent", "research-report"],
                        "metadata": {
                            "task_id": task_id,
                            "stock_code": arguments.stock_code,
                        },
                    },
                )
                evidence = [
                    document_to_evidence(arguments.query, item)
                    for item in documents
                ]
            else:
                vectors = self.embedder.encode([arguments.query])
                if not self._prepared:
                    self.store.prepare(int(vectors.shape[1]), mode="skip")
                    self._prepared = True
                hits = self.store.search(
                    vectors[0],
                    arguments.stock_code,
                    arguments.top_k,
                    query_text=arguments.query,
                    filters={
                        "start_date": arguments.start_date,
                        "end_date": arguments.end_date,
                        "institution": arguments.institution,
                    },
                )
                evidence = [
                    self._to_evidence(arguments.query, hit)
                    for hit in hits
                ]
        except Exception as exc:
            return self._error(task_id, started, "REPORT_SEARCH_UNAVAILABLE", str(exc))
        if not evidence:
            return self._error(task_id, started, "REPORT_DATA_EMPTY", "no report chunks found")
        return ToolResult(
            task_id=task_id,
            success=True,
            evidence=evidence,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    @staticmethod
    def _to_evidence(query: str, hit: RetrievalHit) -> Evidence:
        locator = f"milvus://{COLLECTION_NAME}/{hit.chunk_id}"
        evidence_id = f"report-{hashlib.sha256(locator.encode()).hexdigest()[:16]}"
        return Evidence(
            evidence_id=evidence_id,
            evidence_type="research_report",
            subject=hit.stock_code,
            statement=(
                f"{hit.institution}《{hit.report_title}》第{hit.page_number}页与查询相关："
                f"{hit.text[:160]}"
            ),
            data={
                "query": query,
                "chunk_id": hit.chunk_id,
                "text": hit.text,
                "score": hit.score,
                "retrieval_strategy": hit.retrieval_strategy,
                "dense_score": hit.dense_score,
                "keyword_score": hit.keyword_score,
                "parent_chunk_id": hit.parent_chunk_id,
                "section_title": hit.section_title,
                "content_hash": hit.content_hash,
                "document_version": hit.document_version,
                "stock_code": hit.stock_code,
                "stock_name": hit.stock_name,
                "institution": hit.institution,
                "report_title": hit.report_title,
                "report_date": hit.report_date.isoformat() if hit.report_date else None,
                "date_unknown": hit.date_unknown,
                "page_number": hit.page_number,
            },
            source=SourceReference(
                source_type="milvus",
                locator=locator,
                observed_at=datetime.now(UTC),
                metadata={
                    "collection": COLLECTION_NAME,
                    "document_id": hit.document_id,
                    "source_path": hit.source_path,
                    "page_number": hit.page_number,
                    "score": hit.score,
                    "retrieval_strategy": hit.retrieval_strategy,
                    "content_hash": hit.content_hash,
                    "document_version": hit.document_version,
                },
            ),
        )

    @staticmethod
    def _error(task_id: str, started: float, code: str, message: str) -> ToolResult:
        return ToolResult(
            task_id=task_id,
            success=False,
            error_code=code,
            error_message=message,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
