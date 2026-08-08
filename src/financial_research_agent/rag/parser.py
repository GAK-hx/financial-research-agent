from __future__ import annotations

import hashlib
import re
from pathlib import Path

from financial_research_agent.rag.manifest import metadata_for
from financial_research_agent.rag.models import ReportChunk, ReportDocument

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
PARENT_CHUNK_SIZE = 1800


def clean_page_text(text: str) -> str:
    lines: list[str] = []
    previous = None
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line or line == previous:
            continue
        if re.fullmatch(r"[-—]?\s*\d+\s*[-—]?", line):
            continue
        lines.append(line)
        previous = line
    return "\n".join(lines)


def split_page(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if size <= overlap or overlap < 0:
        raise ValueError("chunk size must be greater than overlap")
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        hard_end = min(start + size, len(text))
        end = hard_end
        if hard_end < len(text):
            candidates = [text.rfind(separator, start + size // 2, hard_end) for separator in ["\n", "。", "；"]]
            boundary = max(candidates)
            if boundary > start:
                end = boundary + 1
        chunk = text[start:end].strip()
        if len(chunk) >= 20:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _looks_like_heading(line: str) -> bool:
    line = line.strip()
    if not line or len(line) > 70:
        return False
    if re.match(r"^(?:\d+(?:\.\d+)*|[一二三四五六七八九十]+)[、.．\s]", line):
        return True
    normalized = line.strip("：: ")
    return normalized in {
        "摘要",
        "核心观点",
        "投资要点",
        "公司动态",
        "行业观点",
        "盈利预测",
        "风险提示",
        "财务数据",
    }


def structured_sections(text: str, *, default_title: str) -> list[tuple[str, str]]:
    """Split one page into heading-aware sections without inventing headings."""
    sections: list[tuple[str, str]] = []
    title = default_title
    body: list[str] = []
    for line in text.splitlines():
        if _looks_like_heading(line):
            if body:
                sections.append((title, "\n".join(body).strip()))
            title = line.strip()
            body = []
        else:
            body.append(line)
    if body:
        sections.append((title, "\n".join(body).strip()))
    return [(heading, content) for heading, content in sections if len(content) >= 20]


def parse_report(path: Path) -> tuple[ReportDocument, list[ReportChunk]]:
    import fitz

    metadata = metadata_for(path)
    document_id = hashlib.sha256(path.name.encode()).hexdigest()[:20]
    with fitz.open(path) as pdf:
        if pdf.page_count <= 0:
            raise ValueError(f"PDF has no pages: {path}")
        page_texts = [clean_page_text(page.get_text("text")) for page in pdf]
        document_hash = hashlib.sha256(
            "\n\f\n".join(page_texts).encode("utf-8")
        ).hexdigest()
        document = ReportDocument(
            document_id=document_id,
            **metadata,
            date_unknown=metadata["report_date"] is None,
            source_path=str(path),
            page_count=pdf.page_count,
            content_hash=document_hash,
            document_version=document_hash[:12],
        )
    chunks: list[ReportChunk] = []
    ordinal = 0
    for page_index, page_text in enumerate(page_texts):
        for section_index, (section_title, section_text) in enumerate(
            structured_sections(page_text, default_title=f"第{page_index + 1}页")
        ):
            parents = split_page(section_text, size=PARENT_CHUNK_SIZE, overlap=0)
            for parent_index, parent_text in enumerate(parents):
                parent_identity = (
                    f"{document_id}:{document.document_version}:{page_index + 1}:"
                    f"{section_index}:{parent_index}:{parent_text}"
                )
                parent_id = hashlib.sha256(parent_identity.encode()).hexdigest()[:32]
                for child_index, text in enumerate(split_page(parent_text)):
                    identity = f"{parent_id}:{child_index}:{text}"
                    content_hash = hashlib.sha256(text.encode()).hexdigest()
                    chunks.append(
                        ReportChunk(
                            chunk_id=hashlib.sha256(identity.encode()).hexdigest()[:32],
                            document_id=document_id,
                            stock_code=document.stock_code,
                            stock_name=document.stock_name,
                            institution=document.institution,
                            report_title=document.report_title,
                            report_date=document.report_date,
                            date_unknown=document.date_unknown,
                            page_number=page_index + 1,
                            source_path=document.source_path,
                            text=text,
                            parent_chunk_id=parent_id,
                            parent_text=parent_text,
                            section_title=section_title,
                            chunk_ordinal=ordinal,
                            content_hash=content_hash,
                            document_version=document.document_version,
                        )
                    )
                    ordinal += 1
    if not chunks:
        raise ValueError(f"PDF produced no valid chunks: {path}")
    return document, chunks


def parse_directory(directory: Path) -> tuple[list[ReportDocument], list[ReportChunk]]:
    paths = sorted(directory.glob("*.pdf"))
    if not paths:
        raise ValueError(f"no registered PDFs found in {directory}")
    documents: list[ReportDocument] = []
    chunks: list[ReportChunk] = []
    for path in paths:
        document, report_chunks = parse_report(path)
        documents.append(document)
        chunks.extend(report_chunks)
    return documents, chunks
