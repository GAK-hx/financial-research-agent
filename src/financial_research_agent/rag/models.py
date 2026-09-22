from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ReportDocument(BaseModel):
    document_id: str
    stock_code: str = Field(pattern=r"^\d{6}$")
    stock_name: str
    institution: str
    report_title: str
    report_date: date | None
    date_unknown: bool
    source_path: str
    page_count: int = Field(gt=0)
    content_hash: str = ""
    document_version: str = "v1"


class ReportChunk(BaseModel):
    chunk_id: str
    document_id: str
    stock_code: str
    stock_name: str
    institution: str
    report_title: str
    report_date: date | None
    date_unknown: bool
    page_number: int = Field(gt=0)
    source_path: str
    text: str = Field(min_length=20, max_length=8000)
    parent_chunk_id: str = ""
    parent_text: str = Field(default="", max_length=12000)
    section_title: str = ""
    chunk_ordinal: int = Field(default=0, ge=0)
    content_hash: str = ""
    document_version: str = "v1"


class RetrievalHit(ReportChunk):
    score: float
    retrieval_strategy: Literal["dense", "keyword", "hybrid"] = "dense"
    dense_score: float | None = None
    keyword_score: float | None = None


class ReportCandidate(BaseModel):
    candidate_id: str = Field(pattern=r"^rpt_[a-f0-9]{16}$")
    document_id: str
    stock_code: str = Field(pattern=r"^\d{6}$")
    stock_name: str
    institution: str
    report_title: str
    report_date: date | None = None
    date_unknown: bool = False
    excerpt: str = Field(max_length=160)
    relevance_score: float
    retrieval_strategy: Literal["dense", "keyword", "hybrid"]
    document_version: str = "v1"
    content_hash: str = ""


class ReportCandidateSet(BaseModel):
    candidate_set_id: str = Field(pattern=r"^rcs_[a-f0-9]{16}$")
    requested_start_date: date | None = None
    requested_end_date: date | None = None
    applied_start_date: date
    applied_end_date: date
    window_expanded: bool = False
    coverage_status: Literal["sufficient", "limited", "empty"]
    candidates: list[ReportCandidate] = Field(default_factory=list, max_length=10)


class ReportSelection(BaseModel):
    candidate_set_id: str = Field(pattern=r"^rcs_[a-f0-9]{16}$")
    candidate_ids: list[str] = Field(min_length=1, max_length=5)
    document_ids: list[str] = Field(min_length=1, max_length=5)
    selection_source: Literal["user", "deterministic_policy"]
    selection_reason: str = Field(min_length=2, max_length=500)

    @model_validator(mode="after")
    def validate_selection(self) -> ReportSelection:
        if len(self.candidate_ids) != len(self.document_ids):
            raise ValueError("candidate and document selection counts differ")
        if len(self.candidate_ids) != len(set(self.candidate_ids)):
            raise ValueError("candidate selection must be unique")
        if len(self.document_ids) != len(set(self.document_ids)):
            raise ValueError("document selection must be unique")
        return self
