from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


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
