from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

import numpy as np

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import (
    Evidence,
    ReportClaim,
    ResearchReport,
    SourceReference,
)
from financial_research_agent.orchestration.interpreter import QueryInterpreter
from financial_research_agent.orchestration.langgraph_runtime import (
    LangGraphResearchService,
    initial_research_state,
    research_graph_config,
)
from financial_research_agent.orchestration.registry import ToolRegistry
from financial_research_agent.orchestration.service import OrchestrationService
from financial_research_agent.rag.models import RetrievalHit
from financial_research_agent.reporting.facts import ReportFactExtractor
from financial_research_agent.reporting.service import ReportingService
from financial_research_agent.reporting.validators import ReportValidator
from financial_research_agent.tools.report_search import (
    ReportCandidateSearchInput,
    ReportCandidateSearchTool,
    ReportContentSearchInput,
    ReportContentSearchTool,
)


class _Embedder:
    def encode(self, texts: list[str]) -> np.ndarray:
        return np.asarray([[1.0, 0.0, 0.0] for _ in texts], dtype=np.float32)


class _Store:
    def __init__(self, hits: list[RetrievalHit]) -> None:
        self.hits = hits
        self.filters: list[dict] = []

    def prepare(self, dimension: int, mode: str = "skip") -> None:
        return None

    def search(
        self,
        query_vector: np.ndarray,
        stock_code: str,
        top_k: int,
        *,
        query_text: str | None = None,
        filters: dict | None = None,
    ) -> list[RetrievalHit]:
        filters = filters or {}
        self.filters.append(filters)
        documents = set(filters.get("document_ids") or [])
        return [
            item
            for item in self.hits
            if not documents or item.document_id in documents
        ][:top_k]


def _hit(
    document_id: str,
    report_date: date,
    *,
    chunk_id: str | None = None,
    text: str = "公司渠道改革持续推进，经营质量保持稳定。",
) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk_id or f"chunk-{document_id}",
        document_id=document_id,
        stock_code="600519",
        stock_name="贵州茅台",
        institution=f"机构{document_id[-1]}",
        report_title=f"研报{document_id[-1]}",
        report_date=report_date,
        date_unknown=False,
        page_number=2,
        source_path=f"/private/{document_id}.pdf",
        text=text,
        score=0.9,
        parent_chunk_id=f"parent-{document_id}",
        content_hash=document_id * 4,
    )


class ReportWorkflowToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_window_expands_and_hides_body_path(self) -> None:
        store = _Store(
            [
                _hit("doc1", date(2026, 7, 10)),
                _hit("doc2", date(2026, 3, 1)),
                _hit("doc3", date(2026, 2, 1)),
            ]
        )
        tool = ReportCandidateSearchTool(
            Settings(market_stock_codes="600519"), _Embedder(), store
        )
        result = await tool.execute(
            "candidate",
            ReportCandidateSearchInput(
                stock_code="600519",
                query="最近有哪些研报",
                reference_date=date(2026, 7, 15),
            ),
        )

        self.assertTrue(result.success, result.error_message)
        self.assertTrue(result.evidence[0].data["window_expanded"])
        self.assertTrue(
            all("source_path" not in item.source.metadata for item in result.evidence)
        )
        self.assertTrue(
            all("text" not in item.data for item in result.evidence)
        )

    async def test_content_is_limited_to_selected_document(self) -> None:
        store = _Store(
            [_hit("doc1", date(2026, 7, 10)), _hit("doc2", date(2026, 7, 9))]
        )
        tool = ReportContentSearchTool(
            Settings(market_stock_codes="600519"), _Embedder(), store
        )
        result = await tool.execute(
            "content",
            ReportContentSearchInput(
                stock_code="600519",
                query="总结观点",
                candidate_ids=["rpt_0123456789abcdef"],
                document_ids=["doc2"],
            ),
        )

        self.assertTrue(result.success, result.error_message)
        self.assertEqual({item.data["document_id"] for item in result.evidence}, {"doc2"})
        self.assertTrue(
            all("source_path" not in item.source.metadata for item in result.evidence)
        )


class ReportWorkflowValidationTests(unittest.TestCase):
    def test_interpreter_separates_listing_and_deep_analysis(self) -> None:
        interpreter = QueryInterpreter(today=date(2026, 7, 15))
        listing = interpreter.interpret("贵州茅台最近有哪些研报")
        deep = interpreter.interpret("总结贵州茅台研报目标价和评级")

        self.assertEqual(listing.report_request.mode, "candidate_only")
        self.assertEqual(deep.report_request.mode, "deep")
        self.assertEqual(
            set(deep.report_request.deep_topics),
            {"viewpoint", "target_price", "rating"},
        )

    def test_typed_fact_and_candidate_scope_validation(self) -> None:
        query = QueryInterpreter(today=date(2026, 7, 15)).interpret(
            "分析贵州茅台研报目标价和评级"
        )
        evidence = Evidence(
            evidence_id="run:report",
            evidence_type="research_report",
            subject="600519",
            statement="示例证券研报第2页包含目标价与评级。",
            data={
                "document_id": "doc1",
                "institution": "示例证券",
                "report_title": "测试研报",
                "report_date": "2026-07-10",
                "page_number": 2,
                "chunk_id": "chunk1",
                "text": "示例证券给予买入评级，目标价为180元。",
            },
            source=SourceReference(
                source_type="milvus",
                locator="milvus://reports/chunk1",
                observed_at=datetime.now(timezone.utc),
                metadata={"document_id": "doc1", "page_number": 2},
            ),
        )
        facts = ReportFactExtractor().extract(
            [evidence], topics=query.report_request.deep_topics
        )
        report = ResearchReport(
            subjects=["600519"],
            summary="示例证券研报给出明确评级和目标价。",
            summary_evidence_ids=[evidence.evidence_id],
            claims=[
                ReportClaim(
                    claim="示例证券给予买入评级，目标价为180元。",
                    evidence_ids=[evidence.evidence_id],
                    fact_ids=[item.fact_id for item in facts],
                    confidence="medium",
                )
            ],
            risks=[
                {
                    "risk": "观点依赖单份研报，存在覆盖局限。",
                    "classification": "model_interpretation",
                    "evidence_ids": [evidence.evidence_id],
                    "confidence": "medium",
                }
            ],
            data_as_of=date(2026, 7, 10),
        )

        result = ReportValidator().validate(
            report,
            query,
            [evidence],
            "run",
            report_facts=facts,
            validation_profile="report_analysis_v2",
            selected_document_ids={"doc1"},
        )

        self.assertTrue(result.passed, result.errors)


class _Reporter:
    async def generate(
        self,
        question: str,
        query,
        evidence: list[Evidence],
        draft=None,
        validation_errors=None,
    ) -> ResearchReport:
        content = next(
            item for item in evidence if item.evidence_type == "research_report"
        )
        facts = ReportFactExtractor().extract(
            evidence, topics=query.report_request.deep_topics
        )
        return ResearchReport(
            subjects=query.stock_codes,
            summary="机构1研报给出明确评级和目标价。",
            summary_evidence_ids=[content.evidence_id],
            claims=[
                ReportClaim(
                    claim="机构1给予买入评级，目标价为180元。",
                    evidence_ids=[content.evidence_id],
                    fact_ids=[item.fact_id for item in facts],
                    confidence="medium",
                )
            ],
            risks=[
                {
                    "risk": "单一研报样本存在覆盖局限。",
                    "classification": "model_interpretation",
                    "evidence_ids": [content.evidence_id],
                    "confidence": "medium",
                }
            ],
        )


class _CandidateReporter:
    async def generate(
        self,
        question: str,
        query,
        evidence: list[Evidence],
        draft=None,
        validation_errors=None,
    ) -> ResearchReport:
        candidate = next(
            item for item in evidence if item.evidence_type == "report_candidate"
        )
        return ResearchReport(
            subjects=query.stock_codes,
            summary="当前索引中存在一份候选研报。",
            summary_evidence_ids=[candidate.evidence_id],
            claims=[
                ReportClaim(
                    claim="候选研报由机构1发布。",
                    evidence_ids=[candidate.evidence_id],
                    confidence="medium",
                )
            ],
            risks=[
                {
                    "risk": "候选数量较少，索引覆盖有限。",
                    "classification": "model_interpretation",
                    "evidence_ids": [candidate.evidence_id],
                    "confidence": "medium",
                }
            ],
        )


class ReportWorkflowGraphTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_listing_never_reads_report_body(self) -> None:
        settings = Settings(
            market_stock_codes="600519",
            checkpoint_backend="memory",
            max_report_revisions=0,
            evaluation_reference_date=date(2026, 7, 15),
        )
        store = _Store([_hit("doc1", date(2026, 7, 10))])
        registry = ToolRegistry()
        registry.register(
            ReportCandidateSearchTool(settings, _Embedder(), store)
        )
        registry.register(ReportContentSearchTool(settings, _Embedder(), store))
        orchestration = OrchestrationService(
            settings,
            registry,
            interpreter=QueryInterpreter(today=date(2026, 7, 15)),
        )
        service = LangGraphResearchService(
            settings,
            orchestration=orchestration,
            reporting=ReportingService(
                settings, _CandidateReporter(), ReportValidator()
            ),
        )
        state = initial_research_state(
            "贵州茅台最近有哪些研报", "candidate-graph"
        )
        result = await service.graph.ainvoke(
            state, research_graph_config(state["thread_id"])
        )

        self.assertEqual(result["reporting_status"], "completed")
        self.assertEqual(
            [item["task_id"] for item in result["tool_results"]],
            ["report_candidates"],
        )
        self.assertFalse(result["report_content_retrieved"])
        self.assertEqual(result["report_validation_profile"], "candidate_listing_v1")

    async def test_deep_report_path_is_candidate_then_controlled_content(self) -> None:
        settings = Settings(
            market_stock_codes="600519",
            checkpoint_backend="memory",
            max_report_revisions=0,
            evaluation_reference_date=date(2026, 7, 15),
        )
        store = _Store(
            [
                _hit(
                    "doc1",
                    date(2026, 7, 10),
                    text=(
                        "机构1认为公司经营质量稳定，给予买入评级，"
                        "目标价为180元。"
                    ),
                )
            ]
        )
        registry = ToolRegistry()
        registry.register(
            ReportCandidateSearchTool(settings, _Embedder(), store)
        )
        registry.register(ReportContentSearchTool(settings, _Embedder(), store))
        orchestration = OrchestrationService(
            settings,
            registry,
            interpreter=QueryInterpreter(today=date(2026, 7, 15)),
        )
        service = LangGraphResearchService(
            settings,
            orchestration=orchestration,
            reporting=ReportingService(settings, _Reporter(), ReportValidator()),
        )
        state = initial_research_state(
            "总结贵州茅台研报目标价和评级", "report-graph"
        )
        result = await service.graph.ainvoke(
            state, research_graph_config(state["thread_id"])
        )

        self.assertEqual(
            result["reporting_status"], "completed", result["validation"]
        )
        self.assertEqual(
            [item["task_id"] for item in result["tool_results"]],
            ["report_candidates", "report_content"],
        )
        self.assertTrue(result["report_content_retrieved"])
        self.assertEqual(
            {item["fact_type"] for item in result["report_facts"]},
            {"target_price", "rating"},
        )
        self.assertEqual(
            result["report_selection"]["document_ids"], ["doc1"]
        )


if __name__ == "__main__":
    unittest.main()
