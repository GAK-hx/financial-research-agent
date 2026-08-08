from __future__ import annotations

import asyncio
import json
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

import numpy as np
import pyarrow as pa
from pydantic import BaseModel

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import (
    AnalysisPlan,
    AnalysisTask,
    Evidence,
    Intent,
    QuerySpec,
    ReportClaim,
    ResearchReport,
    SourceReference,
    ToolName,
    ToolResult,
)
from financial_research_agent.orchestration.executor import PlanExecutor
from financial_research_agent.orchestration.registry import ToolRegistry
from financial_research_agent.providers.model import OpenAICompatibleProvider
from financial_research_agent.reporting.validators import ReportValidator
from financial_research_agent.tools.base import FinancialTool, ToolDefinition
from financial_research_agent.tools.market import MarketQueryInput, MarketQueryTool
from financial_research_agent.tools.report_search import ReportSearchInput, ReportSearchTool


class EmptyMarketRepository:
    def query_daily(self, stock_code: str, start_date: date, end_date: date):
        return pa.table({})

    def current_snapshot_id(self):
        return None


class FakeEmbedder:
    def encode(self, texts: list[str]) -> np.ndarray:
        return np.asarray([[1.0, 0.0]], dtype=np.float32)


class OfflineStore:
    def prepare(self, dimension: int, mode: str = "skip") -> None:
        raise RuntimeError("milvus offline")


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": "{invalid-json"}}]}


class FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def post(self, url: str, headers: dict, json: dict) -> FakeResponse:
        return FakeResponse()


class AnyInput(BaseModel):
    stock_code: str


class HangingTool(FinancialTool):
    definition = ToolDefinition(
        name="market_query",
        description="fault injection timeout tool",
        timeout_seconds=0,
        data_domain="market",
    )
    input_model = AnyInput

    async def execute(self, task_id: str, arguments: AnyInput) -> ToolResult:
        await asyncio.sleep(0.1)
        return ToolResult(task_id=task_id, success=True, latency_ms=100)


class FaultInjectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_market_data_is_structured(self):
        tool = MarketQueryTool(Settings(), EmptyMarketRepository())
        result = await tool.execute(
            "empty-market",
            MarketQueryInput(
                stock_code="600519",
                start_date=date(1990, 1, 1),
                end_date=date(1990, 1, 2),
            ),
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "MARKET_DATA_EMPTY")

    async def test_milvus_unavailable_is_structured(self):
        tool = ReportSearchTool(Settings(), FakeEmbedder(), OfflineStore())
        result = await tool.execute(
            "offline-report",
            ReportSearchInput(stock_code="600519", query="渠道改革"),
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "REPORT_SEARCH_UNAVAILABLE")

    async def test_model_invalid_json_is_explicit_failure(self):
        settings = Settings(
            model_name="deepseek-v4-flash",
            model_api_key="test-key",
            model_base_url="https://api.deepseek.com",
        )
        query = QuerySpec(
            stock_codes=["600519"],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 7, 15),
            intent=Intent.MARKET,
        )
        with patch(
            "financial_research_agent.providers.model.httpx.AsyncClient",
            return_value=FakeClient(),
        ):
            with self.assertRaises(json.JSONDecodeError):
                await OpenAICompatibleProvider(settings).create_plan("分析贵州茅台", query, [])

    async def test_tool_timeout_is_structured(self):
        registry = ToolRegistry()
        registry.register(HangingTool())
        query = QuerySpec(stock_codes=["600519"], intent=Intent.MARKET)
        plan = AnalysisPlan(
            query=query,
            tasks=[
                AnalysisTask(
                    task_id="timeout",
                    tool_name=ToolName.MARKET_QUERY,
                    arguments={"stock_code": "600519"},
                )
            ],
        )
        result = (await PlanExecutor(registry, max_retries=0).execute(plan))[0]
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "TOOL_TIMEOUT")

    async def test_forged_citation_is_rejected(self):
        run_id = "fault-run"
        query = QuerySpec(stock_codes=["600519"], intent=Intent.REPORT)
        evidence = Evidence(
            evidence_id=f"{run_id}:report-1",
            evidence_type="research_report",
            subject="600519",
            statement="华鑫证券研报第2页讨论渠道改革。",
            data={"institution": "华鑫证券", "page_number": 2},
            source=SourceReference(
                source_type="milvus",
                locator="milvus://test/chunk-1",
                observed_at=datetime.now(timezone.utc),
                metadata={"page_number": 2},
            ),
        )
        report = ResearchReport(
            subjects=["600519"],
            summary="研报摘要",
            summary_evidence_ids=[evidence.evidence_id],
            claims=[
                ReportClaim(
                    claim="华鑫证券指出公司推进渠道改革。",
                    evidence_ids=[f"{run_id}:forged"],
                    confidence="medium",
                )
            ],
            risks=[{"risk": "研报观点存在不确定性。", "classification": "model_interpretation", "evidence_ids": [evidence.evidence_id], "confidence": "medium"}],
        )
        result = ReportValidator().validate(report, query, [evidence], run_id)
        self.assertFalse(result.passed)
        self.assertTrue(any("CITATION_UNKNOWN" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
