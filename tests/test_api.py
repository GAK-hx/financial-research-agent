from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from financial_research_agent.api import create_app
from financial_research_agent.api_models import HealthComponent, HealthResponse
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
    ValidationResult,
)
from financial_research_agent.observability import redact
from financial_research_agent.orchestration.context import (
    OrchestrationResult,
    RunStage,
    StageTiming,
)
from financial_research_agent.reporting.service import ReportingResult
from financial_research_agent.research import ResearchRunResult


class FakeRegistry:
    def schemas(self):
        return [
            {
                "name": "financial_query",
                "description": "financial",
                "input_schema": {"type": "object"},
            }
        ]

    def get(self, name: str):
        return SimpleNamespace(definition=SimpleNamespace(version="1.0.0"))


class FakeResearchService:
    def __init__(self, result: ResearchRunResult):
        self.result = result

    async def analyze(self, question: str, **kwargs) -> ResearchRunResult:
        return self.result


def research_result(reporting_status: str = "completed") -> ResearchRunResult:
    run_id = "api-run-001"
    query = QuerySpec(
        stock_codes=["600519"],
        start_date=date(2025, 1, 1),
        end_date=date(2026, 1, 1),
        intent=Intent.FINANCIAL,
        dimensions=["financial_growth"],
    )
    plan = AnalysisPlan(
        query=query,
        tasks=[
            AnalysisTask(
                task_id="financial",
                tool_name=ToolName.FINANCIAL_QUERY,
                arguments={
                    "stock_code": "600519",
                    "start_date": "2025-01-01",
                    "end_date": "2026-01-01",
                },
            )
        ],
    )
    evidence = Evidence(
        evidence_id=f"{run_id}:financial-1",
        evidence_type="financial",
        subject="600519",
        statement="600519最新报告期营收为100元。",
        data={"data_as_of": "2025-12-31", "revenue": 100.0},
        source=SourceReference(
            source_type="iceberg",
            locator="iceberg://financial.metrics",
            observed_at=datetime.now(timezone.utc),
        ),
    )
    orchestration = OrchestrationResult(
        run_id=run_id,
        success=True,
        stage=RunStage.COMPLETED,
        query=query,
        plan=plan,
        planner_source="rule_fallback",
        tool_results=[
            ToolResult(task_id="financial", success=True, evidence=[evidence], latency_ms=12)
        ],
        evidence=[evidence],
        timings=[StageTiming(stage=RunStage.EXECUTING, duration_ms=12)],
        errors=[],
    )
    if reporting_status == "completed":
        report = ResearchReport(
            subjects=["600519"],
            summary="财务摘要",
            summary_evidence_ids=[evidence.evidence_id],
            claims=[
                ReportClaim(
                    claim="600519营收为100元。",
                    evidence_ids=[evidence.evidence_id],
                    confidence="high",
                )
            ],
            risks=[{"risk": "数据口径风险。", "classification": "model_interpretation", "evidence_ids": [evidence.evidence_id], "confidence": "medium"}],
            data_as_of=date(2025, 12, 31),
        )
        reporting = ReportingResult(
            status="completed",
            report=report,
            validation=ValidationResult(passed=True),
            attempts=1,
            timings={"generate_report": 8, "validate_report": 1},
        )
    else:
        reporting = ReportingResult(
            status="generation_failed",
            attempts=1,
            timings={"generate_report": 1},
            errors=["ProviderUnavailable:model provider is not configured"],
        )
    return ResearchRunResult(
        success=reporting_status == "completed",
        orchestration=orchestration,
        reporting=reporting,
    )


class ApiTests(unittest.TestCase):
    def client(self, result: ResearchRunResult) -> TestClient:
        app = create_app()
        app.state.settings = Settings(
            model_api_key="super-secret-key",
            analyze_via_jobs=False,
        )
        app.state.registry = FakeRegistry()
        app.state.research_service = FakeResearchService(result)
        app.state.health_override = HealthResponse(
            status="degraded",
            version="0.1.0",
            model_configured=False,
            components={"configuration": HealthComponent(status="ready")},
        )
        return TestClient(app)

    def test_health_tools_and_successful_analyze(self):
        with self.client(research_result()) as client:
            health = client.get("/health")
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json()["status"], "degraded")
            tools = client.get("/tools")
            self.assertEqual(tools.status_code, 200)
            self.assertEqual(tools.json()["tools"][0]["name"], "financial_query")
            response = client.post("/analyze", json={"question": "贵州茅台财务如何"})
        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(payload["run_id"], "api-run-001")
        self.assertEqual(payload["tool_status"][0]["tool_name"], "financial_query")
        self.assertTrue(payload["validation"]["passed"])
        self.assertIn("api_total", payload["timings"])
        self.assertIn("x-request-id", response.headers)

    def test_partial_failure_keeps_run_and_evidence(self):
        with self.client(research_result("generation_failed")) as client:
            response = client.post("/analyze", json={"question": "贵州茅台财务如何"})
        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["reporting_status"], "generation_failed")
        self.assertEqual(payload["error"]["code"], "REPORT_GENERATION_FAILED")
        self.assertEqual(payload["error"]["run_id"], payload["run_id"])
        self.assertEqual(len(payload["evidence"]), 1)

    def test_invalid_request_has_structured_error_and_run_id(self):
        with self.client(research_result()) as client:
            response = client.post("/analyze", json={"question": ""})
        payload = response.json()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(payload["error"]["code"], "REQUEST_VALIDATION_ERROR")
        self.assertTrue(payload["error"]["run_id"])

    def test_redaction_hides_secrets_recursively(self):
        payload = redact(
            {
                "model_api_key": "super-secret-key",
                "nested": {"authorization": "Bearer secret", "stock_code": "600519"},
            }
        )
        self.assertEqual(payload["model_api_key"], "[REDACTED]")
        self.assertEqual(payload["nested"]["authorization"], "[REDACTED]")
        self.assertEqual(payload["nested"]["stock_code"], "600519")


if __name__ == "__main__":
    unittest.main()
