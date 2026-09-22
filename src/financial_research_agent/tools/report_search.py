from __future__ import annotations

import hashlib
import time
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

import numpy as np
from pydantic import BaseModel, Field, model_validator

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import Evidence, SourceReference, ToolResult
from financial_research_agent.rag.embedding import BgeEmbeddingModel
from financial_research_agent.rag.models import (
    ReportCandidate,
    ReportCandidateSet,
    RetrievalHit,
)
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
    title_keywords: list[str] = Field(default_factory=list, max_length=8)


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


def report_candidate_id(document_id: str, document_version: str) -> str:
    digest = hashlib.sha256(
        f"{document_id}:{document_version}".encode("utf-8")
    ).hexdigest()[:16]
    return f"rpt_{digest}"


class ReportCandidateSearchInput(BaseModel):
    stock_code: str = Field(pattern=r"^\d{6}$")
    query: str = Field(min_length=2, max_length=500)
    reference_date: date
    top_k: int = Field(default=5, ge=1, le=10)
    minimum_candidates: int = Field(default=3, ge=1, le=5)
    explicit_date_range: bool = False
    start_date: date | None = None
    end_date: date | None = None
    institution: str | None = Field(default=None, min_length=2, max_length=128)
    title_keywords: list[str] = Field(default_factory=list, max_length=8)
    allow_unknown_date: bool = False


class ReportCandidateSearchTool(FinancialTool):
    definition = ToolDefinition(
        name="report_candidate_search",
        version="1.0.0",
        description=(
            "List compact, document-level research-report candidates. "
            "It does not return report body text for analytical claims."
        ),
        timeout_seconds=30,
        max_rows=10,
        data_domain="research_report",
    )
    input_model = ReportCandidateSearchInput

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

    async def execute(
        self, task_id: str, arguments: ReportCandidateSearchInput
    ) -> ToolResult:
        started = time.perf_counter()
        if arguments.stock_code not in self.settings.stock_codes:
            return ReportSearchTool._error(
                task_id,
                started,
                "STOCK_NOT_ALLOWED",
                "stock is outside configured pool",
            )
        requested_end = arguments.end_date or arguments.reference_date
        requested_start = arguments.start_date
        if arguments.explicit_date_range:
            applied_start = requested_start or (requested_end - timedelta(days=90))
        else:
            applied_start = requested_end - timedelta(days=90)
        expanded = False
        try:
            vector = self._query_vector(arguments.query)
            hits = self._search(
                vector,
                arguments,
                start_date=applied_start,
                end_date=requested_end,
            )
            candidates = self._candidates(
                hits,
                arguments,
                start_date=applied_start,
                end_date=requested_end,
            )
            if (
                not arguments.explicit_date_range
                and len(candidates) < arguments.minimum_candidates
            ):
                expanded = True
                applied_start = requested_end - timedelta(days=180)
                hits = self._search(
                    vector,
                    arguments,
                    start_date=applied_start,
                    end_date=requested_end,
                )
                candidates = self._candidates(
                    hits,
                    arguments,
                    start_date=applied_start,
                    end_date=requested_end,
                )
        except Exception as exc:
            return ReportSearchTool._error(
                task_id, started, "REPORT_SEARCH_UNAVAILABLE", str(exc)
            )
        if not candidates:
            return ReportSearchTool._error(
                task_id,
                started,
                "REPORT_DATA_EMPTY",
                "no report candidates found in the applied date window",
            )
        candidate_set = self._candidate_set(
            arguments,
            candidates,
            applied_start=applied_start,
            applied_end=requested_end,
            expanded=expanded,
        )
        evidence = [
            self._to_candidate_evidence(candidate_set, item, rank=index)
            for index, item in enumerate(candidate_set.candidates, start=1)
        ]
        return ToolResult(
            task_id=task_id,
            success=True,
            evidence=evidence,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def _query_vector(self, query: str) -> np.ndarray:
        vectors = np.asarray(self.embedder.encode([query]))
        if vectors.ndim != 2 or len(vectors) != 1:
            raise ValueError("retriever embedding must contain one vector")
        if not self._prepared:
            self.store.prepare(int(vectors.shape[1]), mode="skip")
            self._prepared = True
        return vectors[0]

    def _search(
        self,
        vector: np.ndarray,
        arguments: ReportCandidateSearchInput,
        *,
        start_date: date,
        end_date: date,
    ) -> list[RetrievalHit]:
        return self.store.search(
            vector,
            arguments.stock_code,
            min(max(arguments.top_k * 6, 12), 30),
            query_text=arguments.query,
            filters={
                "start_date": start_date,
                "end_date": end_date,
                "institution": arguments.institution,
            },
        )

    @staticmethod
    def _candidates(
        hits: list[RetrievalHit],
        arguments: ReportCandidateSearchInput,
        *,
        start_date: date,
        end_date: date,
    ) -> list[ReportCandidate]:
        by_document: dict[str, ReportCandidate] = {}
        for hit in hits:
            if hit.stock_code != arguments.stock_code:
                continue
            if hit.date_unknown and not arguments.allow_unknown_date:
                continue
            if hit.report_date and not start_date <= hit.report_date <= end_date:
                continue
            if arguments.institution and arguments.institution not in hit.institution:
                continue
            if arguments.title_keywords and not all(
                keyword in hit.report_title for keyword in arguments.title_keywords
            ):
                continue
            candidate = ReportCandidate(
                candidate_id=report_candidate_id(
                    hit.document_id, hit.document_version
                ),
                document_id=hit.document_id,
                stock_code=hit.stock_code,
                stock_name=hit.stock_name,
                institution=hit.institution,
                report_title=hit.report_title,
                report_date=hit.report_date,
                date_unknown=hit.date_unknown,
                excerpt=(hit.text or hit.parent_text)[:160],
                relevance_score=hit.score,
                retrieval_strategy=hit.retrieval_strategy,
                document_version=hit.document_version,
                content_hash=hit.content_hash,
            )
            current = by_document.get(hit.document_id)
            if current is None or candidate.relevance_score > current.relevance_score:
                by_document[hit.document_id] = candidate
        ordered = sorted(
            by_document.values(),
            key=lambda item: (
                -item.relevance_score,
                -(item.report_date.toordinal() if item.report_date else 0),
                item.candidate_id,
            ),
        )
        return ordered[: arguments.top_k]

    @staticmethod
    def _candidate_set(
        arguments: ReportCandidateSearchInput,
        candidates: list[ReportCandidate],
        *,
        applied_start: date,
        applied_end: date,
        expanded: bool,
    ) -> ReportCandidateSet:
        identity = "|".join(
            [
                arguments.stock_code,
                applied_start.isoformat(),
                applied_end.isoformat(),
                *[item.candidate_id for item in candidates],
            ]
        )
        return ReportCandidateSet(
            candidate_set_id=(
                "rcs_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
            ),
            requested_start_date=arguments.start_date,
            requested_end_date=arguments.end_date,
            applied_start_date=applied_start,
            applied_end_date=applied_end,
            window_expanded=expanded,
            coverage_status=(
                "sufficient"
                if len(candidates) >= arguments.minimum_candidates
                else "limited"
            ),
            candidates=candidates,
        )

    @staticmethod
    def _to_candidate_evidence(
        candidate_set: ReportCandidateSet,
        candidate: ReportCandidate,
        *,
        rank: int,
    ) -> Evidence:
        locator = (
            f"milvus://{COLLECTION_NAME}/documents/{candidate.candidate_id}"
        )
        return Evidence(
            evidence_id=f"report-candidate-{candidate.candidate_id[4:]}",
            evidence_type="report_candidate",
            subject=candidate.stock_code,
            statement=(
                f"候选{rank}：{candidate.institution}《{candidate.report_title}》"
                f"，日期{candidate.report_date or '未知'}。"
            ),
            data={
                **candidate.model_dump(mode="json"),
                "candidate_set_id": candidate_set.candidate_set_id,
                "rank": rank,
                "requested_start_date": candidate_set.requested_start_date,
                "requested_end_date": candidate_set.requested_end_date,
                "applied_start_date": candidate_set.applied_start_date,
                "applied_end_date": candidate_set.applied_end_date,
                "window_expanded": candidate_set.window_expanded,
                "coverage_status": candidate_set.coverage_status,
            },
            source=SourceReference(
                source_type="milvus",
                locator=locator,
                observed_at=datetime.now(UTC),
                metadata={
                    "collection": COLLECTION_NAME,
                    "document_id": candidate.document_id,
                    "content_hash": candidate.content_hash,
                    "document_version": candidate.document_version,
                },
            ),
        )


class ReportContentSearchInput(BaseModel):
    stock_code: str = Field(pattern=r"^\d{6}$")
    query: str = Field(min_length=2, max_length=500)
    candidate_ids: list[str] = Field(min_length=1, max_length=5)
    document_ids: list[str] = Field(min_length=1, max_length=5)
    top_k_per_document: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def validate_selection(self) -> ReportContentSearchInput:
        if len(self.candidate_ids) != len(self.document_ids):
            raise ValueError("candidate and document selection counts differ")
        if len(self.candidate_ids) != len(set(self.candidate_ids)):
            raise ValueError("candidate selection must be unique")
        if len(self.document_ids) != len(set(self.document_ids)):
            raise ValueError("document selection must be unique")
        if any(
            not candidate_id.startswith("rpt_")
            or len(candidate_id) != 20
            for candidate_id in self.candidate_ids
        ):
            raise ValueError("candidate id format is invalid")
        return self


class ReportContentSearchTool(ReportSearchTool):
    definition = ToolDefinition(
        name="report_content_search",
        version="1.0.0",
        description=(
            "Retrieve page-addressable body evidence only for report documents "
            "selected by the controlled report workflow."
        ),
        timeout_seconds=30,
        max_rows=15,
        data_domain="research_report",
    )
    input_model = ReportContentSearchInput

    async def execute(
        self, task_id: str, arguments: ReportContentSearchInput
    ) -> ToolResult:
        started = time.perf_counter()
        if arguments.stock_code not in self.settings.stock_codes:
            return self._error(
                task_id,
                started,
                "STOCK_NOT_ALLOWED",
                "stock is outside configured pool",
            )
        if len(arguments.candidate_ids) != len(arguments.document_ids):
            return self._error(
                task_id,
                started,
                "REPORT_SELECTION_INVALID",
                "candidate and document selection counts differ",
            )
        try:
            vectors = np.asarray(self.embedder.encode([arguments.query]))
            if vectors.ndim != 2 or len(vectors) != 1:
                raise ValueError("retriever embedding must contain one vector")
            if not self._prepared:
                self.store.prepare(int(vectors.shape[1]), mode="skip")
                self._prepared = True
            evidence: list[Evidence] = []
            for candidate_id, document_id in zip(
                arguments.candidate_ids, arguments.document_ids, strict=True
            ):
                hits = self.store.search(
                    vectors[0],
                    arguments.stock_code,
                    arguments.top_k_per_document,
                    query_text=arguments.query,
                    filters={"document_ids": [document_id]},
                )
                for hit in hits:
                    if hit.document_id != document_id:
                        continue
                    item = self._to_evidence(arguments.query, hit)
                    evidence.append(
                        item.model_copy(
                            update={
                                "data": {
                                    **item.data,
                                    "candidate_id": candidate_id,
                                    "document_id": document_id,
                                },
                                "source": item.source.model_copy(
                                    update={
                                        "metadata": {
                                            key: value
                                            for key, value in item.source.metadata.items()
                                            if key != "source_path"
                                        }
                                    }
                                ),
                            }
                        )
                    )
        except Exception as exc:
            return self._error(
                task_id, started, "REPORT_CONTENT_UNAVAILABLE", str(exc)
            )
        if not evidence:
            return self._error(
                task_id,
                started,
                "REPORT_CONTENT_EMPTY",
                "no body chunks found for the selected report candidates",
            )
        return ToolResult(
            task_id=task_id,
            success=True,
            evidence=evidence,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
