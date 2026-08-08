from __future__ import annotations

import unittest
from datetime import date
from tempfile import TemporaryDirectory

import numpy as np
from pydantic import ValidationError

from financial_research_agent.config import Settings
from financial_research_agent.rag.models import ReportChunk, RetrievalHit
from financial_research_agent.rag.parser import clean_page_text, split_page, structured_sections
from financial_research_agent.rag.store import SqliteKeywordReportStore
from financial_research_agent.tools.report_search import ReportSearchInput, ReportSearchTool


class FakeEmbedder:
    def encode(self, texts: list[str]) -> np.ndarray:
        return np.asarray([[1.0, 0.0, 0.0] for _ in texts], dtype=np.float32)


class FakeStore:
    def __init__(self, hits: list[RetrievalHit] | None = None, error: Exception | None = None):
        self.hits = hits or []
        self.error = error
        self.prepared_dimension = None
        self.search_stock_code = None

    def prepare(self, dimension: int, mode: str = "skip") -> None:
        self.prepared_dimension = dimension

    def search(
        self,
        query_vector: np.ndarray,
        stock_code: str,
        top_k: int,
        *,
        query_text: str | None = None,
        filters: dict | None = None,
    ):
        self.search_stock_code = stock_code
        if self.error:
            raise self.error
        return self.hits[:top_k]


def sample_hit(stock_code: str = "600519") -> RetrievalHit:
    return RetrievalHit(
        chunk_id="chunk-1",
        document_id="document-1",
        stock_code=stock_code,
        stock_name="贵州茅台",
        institution="华鑫证券",
        report_title="i茅台持续发力，改革效果初显",
        report_date=date(2026, 5, 2),
        date_unknown=False,
        page_number=2,
        source_path="/data/reports/maotai.pdf",
        text="i茅台渠道改革持续推进，线上渠道收入和用户触达能力得到改善。",
        score=0.82,
    )


class RagParserTests(unittest.TestCase):
    def test_clean_and_split_preserve_useful_text(self):
        cleaned = clean_page_text("1\n标题\n标题\n  正文  内容\n")
        self.assertEqual(cleaned, "标题\n正文 内容")
        chunks = split_page("这是有效正文。" * 100, size=100, overlap=10)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) >= 20 for chunk in chunks))

    def test_invalid_chunk_parameters_fail(self):
        with self.assertRaises(ValueError):
            split_page("有效正文" * 10, size=10, overlap=10)

    def test_heading_aware_sections_preserve_parent_context(self):
        sections = structured_sections(
            "核心观点\n渠道改革持续推进，线上触达能力得到改善。\n风险提示\n需求存在波动风险。",
            default_title="第1页",
        )
        self.assertEqual([item[0] for item in sections], ["核心观点"])
        self.assertIn("渠道改革", sections[0][1])


class KeywordIndexTests(unittest.TestCase):
    def test_incremental_keyword_index_filters_and_retrieves(self):
        with TemporaryDirectory() as directory:
            settings = Settings(
                rag_keyword_index_path=f"{directory}/reports.sqlite"
            )
            store = SqliteKeywordReportStore(settings)
            chunks = [
                ReportChunk(
                    chunk_id="chunk-1",
                    document_id="doc-1",
                    stock_code="600519",
                    stock_name="贵州茅台",
                    institution="示例证券",
                    report_title="渠道跟踪",
                    report_date=date(2026, 5, 2),
                    date_unknown=False,
                    page_number=1,
                    source_path="/reports/demo.pdf",
                    text="线上渠道改革持续推进，用户触达和履约能力得到持续改善。",
                    parent_chunk_id="parent-1",
                    parent_text="核心观点：线上渠道改革持续推进，用户触达能力有所改善。",
                    section_title="核心观点",
                    content_hash="a" * 64,
                    document_version="v1",
                ),
                ReportChunk(
                    chunk_id="chunk-2",
                    document_id="doc-2",
                    stock_code="300750",
                    stock_name="宁德时代",
                    institution="示例证券",
                    report_title="技术跟踪",
                    report_date=date(2026, 4, 22),
                    date_unknown=False,
                    page_number=1,
                    source_path="/reports/demo2.pdf",
                    text="电池技术持续迭代，产品性能和制造效率得到进一步改善。",
                ),
            ]
            self.assertEqual(store.replace(chunks), 2)
            hits = store.search("渠道改革", "600519", 3)
            self.assertEqual([item.chunk_id for item in hits], ["chunk-1"])
            self.assertEqual(hits[0].retrieval_strategy, "keyword")


class ReportSearchToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = Settings(market_stock_codes="600519,300750")

    def test_top_k_is_limited_to_one_through_ten(self):
        with self.assertRaises(ValidationError):
            ReportSearchInput(stock_code="600519", query="渠道改革", top_k=0)
        with self.assertRaises(ValidationError):
            ReportSearchInput(stock_code="600519", query="渠道改革", top_k=11)

    async def test_stock_filter_and_page_evidence(self):
        store = FakeStore([sample_hit()])
        tool = ReportSearchTool(self.settings, FakeEmbedder(), store)
        result = await tool.execute(
            "report-1",
            ReportSearchInput(stock_code="600519", query="i茅台渠道改革", top_k=3),
        )
        self.assertTrue(result.success)
        self.assertEqual(store.search_stock_code, "600519")
        self.assertEqual(store.prepared_dimension, 3)
        self.assertEqual(result.evidence[0].evidence_type, "research_report")
        self.assertEqual(result.evidence[0].data["page_number"], 2)
        self.assertEqual(result.evidence[0].source.source_type, "milvus")

    async def test_disallowed_stock_fails_before_store(self):
        store = FakeStore([sample_hit()])
        tool = ReportSearchTool(self.settings, FakeEmbedder(), store)
        result = await tool.execute(
            "report-2",
            ReportSearchInput(stock_code="000001", query="渠道改革", top_k=3),
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "STOCK_NOT_ALLOWED")
        self.assertIsNone(store.search_stock_code)

    async def test_milvus_failure_is_structured(self):
        tool = ReportSearchTool(
            self.settings, FakeEmbedder(), FakeStore(error=RuntimeError("milvus offline"))
        )
        result = await tool.execute(
            "report-3",
            ReportSearchInput(stock_code="600519", query="渠道改革", top_k=3),
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "REPORT_SEARCH_UNAVAILABLE")
        self.assertIn("milvus offline", result.error_message)

    async def test_empty_result_is_structured(self):
        tool = ReportSearchTool(self.settings, FakeEmbedder(), FakeStore())
        result = await tool.execute(
            "report-4",
            ReportSearchInput(stock_code="600519", query="渠道改革", top_k=3),
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "REPORT_DATA_EMPTY")


if __name__ == "__main__":
    unittest.main()
