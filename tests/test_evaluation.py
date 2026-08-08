from __future__ import annotations

import json
import os
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from financial_research_agent.evaluation.compare_runtimes import compare
from financial_research_agent.evaluation.models import EvaluationCase
from financial_research_agent.evaluation.run import (
    load_dataset,
    load_named_dataset,
)
from financial_research_agent.evaluation.scoring import aggregate, percentile, score_case
from financial_research_agent.evaluation.snapshot import (
    EvaluationSnapshotManifest,
    IcebergSnapshotEntry,
    ReportSnapshotEntry,
)
from financial_research_agent.evaluation.stability import stability_report


def valid_body() -> dict:
    run_id = "eval-run"
    evidence_id = f"{run_id}:indicator-1"
    query = {
        "stock_codes": ["600519"],
        "start_date": "2025-07-15",
        "end_date": "2026-07-15",
        "intent": "market",
        "dimensions": ["return"],
    }
    return {
        "success": True,
        "run_id": run_id,
        "planner_source": "model",
        "semantic_alignment": {"passed": True, "errors": [], "warnings": []},
        "reporting_status": "completed",
        "query_spec": query,
        "plan": {
            "query": query,
            "tasks": [
                {"task_id": "market", "tool_name": "market_query", "arguments": {"stock_code": "600519", "start_date": "2025-07-15", "end_date": "2026-07-15"}, "depends_on": []},
                {"task_id": "indicator", "tool_name": "indicator_calculator", "arguments": {"stock_code": "600519", "start_date": "2025-07-15", "end_date": "2026-07-15"}, "depends_on": ["market"]}
            ],
            "expected_sections": ["market"]
        },
        "tool_status": [{"success": True}, {"success": True}],
        "evidence": [{
            "evidence_id": evidence_id,
            "evidence_type": "indicator",
            "subject": "600519",
            "statement": "600519区间收益率为10.0%。",
            "data": {"period_return": 0.1, "data_as_of": "2026-07-14"},
            "source": {"source_type": "calculation", "locator": "calculation://test", "observed_at": "2026-07-15T00:00:00Z", "metadata": {}}
        }],
        "report": {"subjects": ["600519"], "summary": "行情摘要", "summary_evidence_ids": [evidence_id], "claims": [{"claim": "贵州茅台区间收益率为10.0%。", "evidence_ids": [evidence_id], "confidence": "high"}], "risks": [{"risk": "市场风险。", "classification": "model_interpretation", "evidence_ids": [evidence_id], "confidence": "medium"}], "limitations": [], "data_as_of": "2026-07-14", "disclaimer": "仅供研究参考，不构成投资建议。"},
        "validation": {"passed": True, "errors": [], "warnings": []},
        "timings": {"api_total": 1000},
        "error": None,
    }


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.case = EvaluationCase.model_validate({
            "case_id": "eval-01", "category": "market", "question": "test",
            "expected_intent": "market", "expected_stock_codes": ["600519"],
            "expected_start_date": "2025-07-15", "expected_end_date": "2026-07-15",
            "expected_tools": ["market_query", "indicator_calculator"]
        })

    def test_dataset_has_twenty_unique_cases_and_financial_coverage(self):
        version, cases = load_dataset()
        self.assertEqual(version, "phase1_eval_v1")
        self.assertEqual(len(cases), 20)
        self.assertEqual(len({case.case_id for case in cases}), 20)
        self.assertIn("financial", {case.category for case in cases})

    def test_phase_two_datasets_are_frozen_unique_and_complete(self):
        holdout, holdout_hash = load_named_dataset("holdout")
        stability, stability_hash = load_named_dataset("stability")
        self.assertEqual(len(holdout.cases), 30)
        self.assertEqual(len(stability.cases), 10)
        self.assertEqual(len(holdout_hash), 64)
        self.assertEqual(len(stability_hash), 64)
        self.assertTrue(
            all(
                case.require_harness_controls
                for case in holdout.cases
                if case.expected_success
            )
        )

    def test_private_holdout_is_loaded_only_from_external_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private.json"
            cases = [
                {
                    "case_id": f"private-{index:02d}",
                    "category": "market",
                    "question": f"私有问题{index}",
                    "expected_intent": "market",
                    "expected_stock_codes": ["600519"],
                    "expected_tools": ["market_query", "indicator_calculator"],
                }
                for index in range(1, 21)
            ]
            path.write_text(
                json.dumps(
                    {
                        "dataset_version": "private_v1",
                        "kind": "private_holdout",
                        "as_of_date": "2026-07-15",
                        "frozen_at": "2026-08-08T00:00:00+08:00",
                        "cases": cases,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"EVAL_PRIVATE_HOLDOUT_PATH": str(path)},
            ):
                dataset, digest = load_named_dataset("private_holdout")
            self.assertEqual(len(dataset.cases), 20)
            self.assertEqual(len(digest), 64)

    def test_snapshot_manifest_detects_dataset_or_content_drift(self):
        manifest = EvaluationSnapshotManifest(
            dataset_name="regression",
            dataset_version="phase1_eval_v1",
            dataset_sha256="a" * 64,
            as_of_date="2026-07-15",
            captured_at=datetime.now(timezone.utc),
            business_timezone="Asia/Shanghai",
            iceberg=[
                IcebergSnapshotEntry(table="market.kline_daily", snapshot_id=1),
                IcebergSnapshotEntry(table="financial.metrics", snapshot_id=2),
            ],
            reports=[
                ReportSnapshotEntry(
                    filename="fixture.pdf", sha256="b" * 64, size_bytes=10
                )
            ],
            retrieval={"collection": "research_reports_v1"},
        )
        manifest = manifest.model_copy(
            update={"fingerprint": manifest.content_fingerprint()}
        )
        manifest.verify(
            dataset_sha256="a" * 64,
            as_of_date=manifest.as_of_date,
        )
        with self.assertRaisesRegex(ValueError, "dataset hash"):
            manifest.verify(
                dataset_sha256="c" * 64,
                as_of_date=manifest.as_of_date,
            )
        with self.assertRaisesRegex(ValueError, "Iceberg input drift"):
            manifest.verify_inputs(
                iceberg=[
                    IcebergSnapshotEntry(
                        table="market.kline_daily",
                        snapshot_id=999,
                    ),
                    IcebergSnapshotEntry(
                        table="financial.metrics",
                        snapshot_id=2,
                    ),
                ],
                reports=manifest.reports,
                retrieval=manifest.retrieval,
            )

    def test_valid_case_scores_all_metrics(self):
        score = score_case(self.case, 200, valid_body())
        self.assertTrue(score.task_success, score.errors)
        self.assertTrue(score.intent_accuracy)
        self.assertTrue(score.tool_selection_accuracy)
        self.assertTrue(score.argument_accuracy)
        self.assertTrue(score.citation_accuracy)
        self.assertTrue(score.numeric_consistency)
        self.assertEqual(score.model_calls, 2)

    def test_wrong_tool_number_and_citation_are_detected(self):
        body = deepcopy(valid_body())
        body["plan"]["tasks"] = body["plan"]["tasks"][:1]
        body["report"]["claims"][0]["claim"] = "贵州茅台区间收益率为99.0%。"
        body["report"]["claims"][0]["evidence_ids"] = ["other-run:forged"]
        score = score_case(self.case, 200, body)
        self.assertFalse(score.tool_selection_accuracy)
        self.assertFalse(score.citation_accuracy)
        self.assertFalse(score.numeric_consistency)

    def test_expected_rejection_and_aggregate(self):
        invalid = EvaluationCase(
            case_id="eval-20", category="invalid", question="",
            expected_http_status=422, expected_success=False,
            expected_error_code="REQUEST_VALIDATION_ERROR"
        )
        score = score_case(
            invalid, 422, {"error": {"code": "REQUEST_VALIDATION_ERROR"}}
        )
        self.assertTrue(score.task_success)
        summary = aggregate([score, score])
        self.assertEqual(summary["metrics"]["task_success"]["rate"], 1.0)
        self.assertIsNone(summary["latency_ms"]["p50"])

    def test_percentile_uses_linear_interpolation(self):
        self.assertEqual(percentile([100, 200, 300, 400], 0.5), 250)
        self.assertEqual(percentile([100, 200, 300, 400], 0.95), 385)

    def test_runtime_comparison_distinguishes_regression_and_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / "baseline"
            candidate = root / "candidate"
            baseline.mkdir()
            candidate.mkdir()
            artifact = {
                "case": {"case_id": "eval-01"},
                "http_status": 200,
                "response": {
                    "success": True,
                    "query_spec": {"intent": "market", "stock_codes": ["600519"]},
                    "tool_status": [
                        {"tool_name": "market_query", "success": True}
                    ],
                    "evidence": [
                        {
                            "evidence_type": "market",
                            "subject": "600519",
                        }
                    ],
                    "report": {"summary": "ok"},
                    "validation": {"passed": True},
                    "error": None,
                },
                "score": {"task_success": True},
            }
            (baseline / "eval-01.json").write_text(
                json.dumps(artifact), encoding="utf-8"
            )
            (candidate / "eval-01.json").write_text(
                json.dumps(artifact), encoding="utf-8"
            )
            report = compare(baseline, candidate)
            self.assertEqual(report["regressions"], [])
            self.assertEqual(report["stable_semantic_matches"], 1)

    def test_harness_and_stability_failures_are_visible(self):
        case = self.case.model_copy(
            update={
                "expected_skills": ["market_trend_analysis@1.0.0"],
                "required_evidence_types": ["indicator"],
                "require_harness_controls": True,
            }
        )
        body = valid_body()
        body["selected_skills"] = ["market_trend_analysis@1.0.0"]
        body["completion"] = {"passed": True}
        body["budget"] = {"open_reservations": 0}
        score = score_case(case, 200, body)
        self.assertTrue(score.task_success, score.errors)

        changed = deepcopy(body)
        changed["selected_skills"] = ["unexpected@1.0.0"]
        report = stability_report(
            [
                ("stability-01", 1, body),
                ("stability-01", 2, changed),
                ("stability-01", 3, body),
            ]
        )
        self.assertEqual(report["dimension_rates"]["skills"], 0.0)
        self.assertEqual(report["fully_stable_cases"], 0)

    def test_report_structure_ignores_variable_item_counts(self):
        first = valid_body()
        second = deepcopy(first)
        second["report"]["claims"].append(
            {
                "claim": "另一条有证据的结论。",
                "evidence_ids": ["eval-run:indicator-1"],
                "confidence": "medium",
            }
        )
        second["report"]["limitations"].append("附加限制。")
        report = stability_report(
            [
                ("stability-01", 1, first),
                ("stability-01", 2, second),
            ]
        )
        self.assertEqual(
            report["dimension_rates"]["report_structure"], 1.0
        )


if __name__ == "__main__":
    unittest.main()
