from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import numpy as np
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field, PrivateAttr

from financial_research_agent.domain.models import (
    Evidence,
    SourceReference,
)
from financial_research_agent.rag.models import RetrievalHit
from financial_research_agent.rag.store import COLLECTION_NAME


class LangChainReportRetriever(BaseRetriever):
    """LangChain retrieval interface over the existing Milvus report store."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    stock_code: str
    top_k: int = Field(default=5, ge=1, le=10)
    embedder: Any = Field(exclude=True)
    store: Any = Field(exclude=True)
    filters: dict[str, Any] = Field(default_factory=dict)
    _prepared: bool = PrivateAttr(default=False)

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Any = None,
    ) -> list[Document]:
        vectors = np.asarray(self.embedder.encode([query]))
        if vectors.ndim != 2 or len(vectors) != 1:
            raise ValueError("retriever embedding must contain one vector")
        if not self._prepared:
            self.store.prepare(int(vectors.shape[1]), mode="skip")
            self._prepared = True
        hits = self.store.search(
            vectors[0],
            self.stock_code,
            self.top_k,
            query_text=query,
            filters=self.filters,
        )
        return [retrieval_hit_to_document(hit) for hit in hits]


def retrieval_hit_to_document(hit: RetrievalHit) -> Document:
    locator = f"milvus://{COLLECTION_NAME}/{hit.chunk_id}"
    return Document(
        id=hit.chunk_id,
        page_content=hit.text,
        metadata={
            "source_type": "milvus",
            "source_locator": locator,
            "collection": COLLECTION_NAME,
            "chunk_id": hit.chunk_id,
            "document_id": hit.document_id,
            "stock_code": hit.stock_code,
            "stock_name": hit.stock_name,
            "institution": hit.institution,
            "report_title": hit.report_title,
            "report_date": (
                hit.report_date.isoformat() if hit.report_date else None
            ),
            "date_unknown": hit.date_unknown,
            "page_number": hit.page_number,
            "source_path": hit.source_path,
            "score": hit.score,
            "retrieval_strategy": hit.retrieval_strategy,
            "dense_score": hit.dense_score,
            "keyword_score": hit.keyword_score,
            "parent_chunk_id": hit.parent_chunk_id,
            "section_title": hit.section_title,
            "content_hash": hit.content_hash,
            "document_version": hit.document_version,
        },
    )


def document_to_evidence(query: str, document: Document) -> Evidence:
    metadata = document.metadata
    locator = str(metadata["source_locator"])
    evidence_id = f"report-{hashlib.sha256(locator.encode()).hexdigest()[:16]}"
    return Evidence(
        evidence_id=evidence_id,
        evidence_type="research_report",
        subject=str(metadata["stock_code"]),
        statement=(
            f"{metadata['institution']}《{metadata['report_title']}》"
            f"第{metadata['page_number']}页与查询相关："
            f"{document.page_content[:160]}"
        ),
        data={
            "query": query,
            "chunk_id": metadata["chunk_id"],
            "text": document.page_content,
            "score": metadata["score"],
            "retrieval_strategy": metadata.get("retrieval_strategy", "dense"),
            "dense_score": metadata.get("dense_score"),
            "keyword_score": metadata.get("keyword_score"),
            "parent_chunk_id": metadata.get("parent_chunk_id"),
            "section_title": metadata.get("section_title"),
            "content_hash": metadata.get("content_hash"),
            "document_version": metadata.get("document_version"),
            "stock_code": metadata["stock_code"],
            "stock_name": metadata["stock_name"],
            "institution": metadata["institution"],
            "report_title": metadata["report_title"],
            "report_date": metadata["report_date"],
            "date_unknown": metadata["date_unknown"],
            "page_number": metadata["page_number"],
        },
        source=SourceReference(
            source_type="milvus",
            locator=locator,
            observed_at=datetime.now(UTC),
            metadata={
                "collection": metadata["collection"],
                "document_id": metadata["document_id"],
                "source_path": metadata["source_path"],
                "page_number": metadata["page_number"],
                "score": metadata["score"],
                "retrieval_strategy": metadata.get("retrieval_strategy", "dense"),
                "content_hash": metadata.get("content_hash"),
                "document_version": metadata.get("document_version"),
            },
        ),
    )


def evidence_to_document(evidence: Evidence) -> Document:
    """Rebuild a standard Document for ToolMessage artifacts and downstream UI."""
    if evidence.evidence_type != "research_report":
        raise ValueError("only research report evidence maps to Document")
    data = evidence.data
    return Document(
        id=str(data.get("chunk_id") or evidence.evidence_id),
        page_content=str(data.get("text") or evidence.statement),
        metadata={
            "source_type": evidence.source.source_type,
            "source_locator": evidence.source.locator,
            "collection": evidence.source.metadata.get("collection"),
            "chunk_id": data.get("chunk_id"),
            "document_id": evidence.source.metadata.get("document_id"),
            "stock_code": data.get("stock_code") or evidence.subject,
            "stock_name": data.get("stock_name"),
            "institution": data.get("institution"),
            "report_title": data.get("report_title"),
            "report_date": data.get("report_date"),
            "date_unknown": data.get("date_unknown"),
            "page_number": data.get("page_number"),
            "source_path": evidence.source.metadata.get("source_path"),
            "score": data.get("score"),
            "retrieval_strategy": data.get("retrieval_strategy"),
            "content_hash": data.get("content_hash"),
            "document_version": data.get("document_version"),
            "evidence_id": evidence.evidence_id,
        },
    )
