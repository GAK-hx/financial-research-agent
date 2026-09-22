from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from pydantic import ValidationError

from financial_research_agent.config import Settings
from financial_research_agent.domain.models import (
    Evidence,
    QuerySpec,
    ReportClaim,
    ResearchReport,
    SourceReference,
)
from financial_research_agent.domain.models import Intent
from financial_research_agent.reporting.reporter import EvidenceOnlyReporter
from financial_research_agent.reporting.service import ReportingService
from financial_research_agent.reporting.validators import (
    ReportValidator,
    bind_report_scope,
)

RUN_ID = "run-001"


def query_spec() -> QuerySpec:
    return QuerySpec(
        stock_codes=["600519"],
        start_date=date(2025, 7, 15),
        end_date=date(2026, 7, 15),
        intent=Intent.COMPREHENSIVE,
        dimensions=["return", "institution_view"],
    )


def sample_evidence(include_report: bool = True) -> list[Evidence]:
    items = [
        Evidence(
            evidence_id=f"{RUN_ID}:indicator-1",
            evidence_type="indicator",
            subject="600519",
            statement="600519区间收益率为19.0000%，最大回撤为-8.0000%。",
            data={
                "stock_code": "600519",
                "actual_start": "2025-07-15",
                "actual_end": "2026-07-14",
                "data_as_of": "2026-07-14",
                "period_return": 0.19,
                "max_drawdown": -0.08,
                "formula_version": "market_indicators_v1",
            },
            source=SourceReference(
                source_type="calculation",
                locator="calculation://market_indicators_v1",
                observed_at=datetime.now(timezone.utc),
            ),
        )
    ]
    if include_report:
        items.append(
            Evidence(
                evidence_id=f"{RUN_ID}:report-1",
                evidence_type="research_report",
                subject="600519",
                statement="华鑫证券研报第2页讨论i茅台直营渠道改革。",
                data={
                    "institution": "华鑫证券",
                    "report_title": "i茅台持续发力，改革效果初显",
                    "report_date": "2026-05-02",
                    "page_number": 2,
                    "text": "公司发力直营渠道，稳步推进全面向C战略。",
                    "score": 0.82,
                },
                source=SourceReference(
                    source_type="milvus",
                    locator="milvus://research_reports_v1/chunk-1",
                    observed_at=datetime.now(timezone.utc),
                    metadata={"page_number": 2, "chunk_id": "chunk-1"},
                ),
            )
        )
    return items


def valid_report(evidence: list[Evidence]) -> dict:
    claims = [
        {
            "claim": "贵州茅台区间收益率为19.0%，最大回撤为-8.0%。",
            "evidence_ids": [evidence[0].evidence_id],
            "confidence": "high",
        }
    ]
    if len(evidence) > 1:
        claims.append(
            {
                "claim": "华鑫证券指出公司正在推进i茅台直营渠道改革。",
                "evidence_ids": [evidence[1].evidence_id],
                "confidence": "medium",
            }
        )
    return {
        "subjects": ["600519"],
        "summary": "贵州茅台行情与机构观点综合研究。",
        "summary_evidence_ids": [evidence[0].evidence_id],
        "claims": claims,
        "risks": [
            {
                "risk": "行业需求及渠道改革效果存在不确定性。",
                "classification": "model_interpretation",
                "evidence_ids": [evidence[0].evidence_id],
                "confidence": "medium",
            }
        ],
        "limitations": [
            {
                "limitation": "只覆盖当前Run已获取的数据。",
                "category": "scope",
                "evidence_ids": [],
            }
        ],
        "data_as_of": "2026-07-14",
        "disclaimer": "仅供研究参考，不构成投资建议。",
    }


class SequenceProvider:
    def __init__(self, outputs: list[dict]) -> None:
        self.outputs = outputs
        self.calls = 0
        self.feedback: list[list[str]] = []

    async def create_report(
        self,
        question: str,
        report_context: dict,
        draft: dict | None = None,
        validation_errors: list[str] | None = None,
    ) -> dict:
        self.feedback.append(validation_errors or [])
        output = self.outputs[min(self.calls, len(self.outputs) - 1)]
        self.calls += 1
        return output


class ReportSchemaValidatorTests(unittest.TestCase):
    def setUp(self):
        self.query = query_spec()
        self.evidence = sample_evidence()
        self.validator = ReportValidator()

    def test_claim_without_evidence_is_rejected_by_schema(self):
        with self.assertRaises(ValidationError):
            ReportClaim(claim="无来源结论", evidence_ids=[], confidence="low")

    def test_valid_report_passes(self):
        report = ResearchReport.model_validate(valid_report(self.evidence))
        result = self.validator.validate(report, self.query, self.evidence, RUN_ID)
        self.assertTrue(result.passed, result.errors)

    def test_display_rounding_of_percentage_is_supported(self):
        rounded_evidence = sample_evidence()
        rounded_evidence[0] = rounded_evidence[0].model_copy(
            update={
                "statement": "600519区间收益率为9.68%，最大回撤为-8.0000%。",
                "data": {
                    **rounded_evidence[0].data,
                    "period_return": 0.0968,
                },
            }
        )
        raw = valid_report(rounded_evidence)
        raw["claims"][0]["claim"] = "贵州茅台区间收益率为9.7%，最大回撤为-8.0%。"
        result = self.validator.validate(
            ResearchReport.model_validate(raw), self.query, rounded_evidence, RUN_ID
        )
        self.assertTrue(result.passed, result.errors)

    def test_small_aggregate_rows_support_numbers_and_ignore_metric_windows(self):
        evidence = sample_evidence()
        evidence[0] = evidence[0].model_copy(
            update={
                "data": {
                    **evidence[0].data,
                    "rows": [
                        {
                            "stock_code": "600519",
                            "volatility_20d": 0.30297,
                            "max_drawdown_60d": 0.10445,
                        }
                    ],
                }
            }
        )
        raw = valid_report(evidence)
        raw["summary"] = "贵州茅台20日波动率为30.297%，60日最大回撤为10.445%。"
        raw["claims"][0]["claim"] = (
            "贵州茅台20日波动率为30.297%，60日最大回撤为10.445%。"
        )

        result = self.validator.validate(
            ResearchReport.model_validate(raw), self.query, evidence, RUN_ID
        )

        self.assertTrue(result.passed, result.errors)

    def test_narrative_metric_window_is_not_a_numeric_fact(self):
        raw = valid_report(self.evidence)
        raw["risks"][0]["risk"] = (
            "流动性指标仅反映过去20日情况，可能无法代表长期风险。"
        )

        result = self.validator.validate(
            ResearchReport.model_validate(raw),
            self.query,
            self.evidence,
            RUN_ID,
        )

        self.assertTrue(result.passed, result.errors)

    def test_drawdown_window_and_decline_magnitude_are_supported(self):
        evidence = sample_evidence()
        evidence[0] = evidence[0].model_copy(
            update={
                "data": {
                    **evidence[0].data,
                    "max_drawdown_60d": 0.10445004712896477,
                }
            }
        )
        raw = valid_report(evidence)
        raw["risks"][0]["risk"] = (
            "60日最大回撤为0.1045，表明过去60天内价格曾从高点"
            "下跌10.45%，存在下行风险。"
        )

        result = self.validator.validate(
            ResearchReport.model_validate(raw),
            self.query,
            evidence,
            RUN_ID,
        )

        self.assertTrue(result.passed, result.errors)

    def test_decimal_tail_is_not_misread_as_a_stock_code(self):
        raw = valid_report(self.evidence)
        raw["claims"][0]["claim"] = "贵州茅台Amihud指标为0.000560。"
        evidence = list(self.evidence)
        evidence[0] = evidence[0].model_copy(
            update={"data": {**evidence[0].data, "amihud": 0.000560}}
        )

        result = self.validator.validate(
            ResearchReport.model_validate(raw), self.query, evidence, RUN_ID
        )

        self.assertNotIn("claim[0]:ENTITY_CLAIM_MISMATCH", result.errors)

    def test_unrequested_risk_dimensions_are_bound_to_unknown(self):
        raw = valid_report(self.evidence)
        raw["risk_vector"] = [
            {
                "dimension": "technical",
                "level": "medium",
                "rationale": "有行情证据。",
                "evidence_ids": [self.evidence[0].evidence_id],
            },
            {
                "dimension": "fundamental",
                "level": "low",
                "rationale": "模型自行推断。",
                "evidence_ids": [],
            },
            {
                "dimension": "event",
                "level": "low",
                "rationale": "模型自行推断。",
                "evidence_ids": [],
            },
            {
                "dimension": "data_confidence",
                "level": "medium",
                "rationale": "数据可用。",
                "evidence_ids": [self.evidence[0].evidence_id],
            },
        ]
        screening_query = self.query.model_copy(
            update={
                "intent": Intent.SCREENING,
                "analysis_domains": ["market"],
            }
        )

        bound = bind_report_scope(
            ResearchReport.model_validate(raw), screening_query
        )

        dimensions = {item.dimension: item for item in bound.risk_vector}
        self.assertEqual(dimensions["fundamental"].level, "unknown")
        self.assertEqual(dimensions["fundamental"].evidence_ids, [])
        self.assertEqual(dimensions["event"].level, "unknown")

    def test_chinese_decline_word_preserves_negative_direction(self):
        decline_evidence = sample_evidence()
        decline_evidence[0] = decline_evidence[0].model_copy(
            update={
                "statement": "600519营业收入同比下降9.7039%，最大回撤为-8.0000%。",
                "data": {
                    **decline_evidence[0].data,
                    "revenue_yoy": -0.09703875523675976,
                },
            }
        )
        raw = valid_report(decline_evidence)
        raw["claims"][0]["claim"] = "贵州茅台营业收入同比下降9.7%，最大回撤为-8.0%。"
        result = self.validator.validate(
            ResearchReport.model_validate(raw), self.query, decline_evidence, RUN_ID
        )
        self.assertTrue(result.passed, result.errors)

    def test_price_fall_and_drawdown_magnitude_are_equivalent(self):
        evidence = sample_evidence()
        evidence[0] = evidence[0].model_copy(
            update={
                "statement": (
                    "600519区间收益率为-11.2572%，最大回撤为-23.4679%。"
                ),
                "data": {
                    **evidence[0].data,
                    "period_return": -0.112572,
                    "max_drawdown": -0.234679,
                },
            }
        )
        raw = valid_report(evidence)
        raw["summary"] = "贵州茅台股价下跌11.2572%，最大回撤23.4679%。"
        raw["claims"][0]["claim"] = (
            "贵州茅台股价下跌11.2572%，最大回撤23.4679%。"
        )
        raw["risks"][0] = {
            "risk": "最大回撤超过23%，表明价格波动风险较高。",
            "classification": "model_interpretation",
            "evidence_ids": [evidence[0].evidence_id],
            "confidence": "medium",
        }
        result = self.validator.validate(
            ResearchReport.model_validate(raw), self.query, evidence, RUN_ID
        )
        self.assertTrue(result.passed, result.errors)

    def test_decline_direction_does_not_cross_clause_boundary(self):
        clause_evidence = sample_evidence()
        clause_evidence[0] = clause_evidence[0].model_copy(
            update={
                "statement": "600519营收同比下降1.21%，净利润823.20亿元。",
                "data": {
                    **clause_evidence[0].data,
                    "revenue_yoy": -0.0121,
                    "parent_net_profit": 82_320_000_000,
                },
            }
        )
        raw = valid_report(clause_evidence)
        raw["claims"][0]["claim"] = "贵州茅台营收同比下降1.21%，净利润823.20亿元。"
        result = self.validator.validate(
            ResearchReport.model_validate(raw), self.query, clause_evidence, RUN_ID
        )
        self.assertTrue(result.passed, result.errors)

    def test_dates_and_indicator_window_labels_are_not_claim_values(self):
        market_evidence = sample_evidence()
        market_evidence[0] = market_evidence[0].model_copy(
            update={
                "data": {
                    **market_evidence[0].data,
                    "ma5": 1202.47,
                    "ma20": 1197.29,
                    "relative_volume_20d": 0.97,
                }
            }
        )
        raw = valid_report(market_evidence)
        raw["claims"][0]["claim"] = (
            "2025年7月15日至2026年7月14日，5日均线为1202.47元，"
            "20日均线为1197.29元，20日相对成交量（relative_volume_20d）"
            "为0.97，略低于过去20日均量；相对20日成交量比为0.97，"
            "近期成交量略低于过去20日平均成交量。"
        )
        result = self.validator.validate(
            ResearchReport.model_validate(raw), self.query, market_evidence, RUN_ID
        )
        self.assertTrue(result.passed, result.errors)

    def test_partial_dates_year_ranges_and_evidence_ids_are_not_facts(self):
        market_evidence = sample_evidence()
        raw = valid_report(market_evidence)
        raw["claims"][0]["claim"] = (
            "贵州茅台（600519）在2026年4月15日至7月14日期间，"
            "区间收益率为19.0%，预计2026-2028年持续经营"
            "（数据来源：indicator-3c7db552679a860c）。"
        )
        result = self.validator.validate(
            ResearchReport.model_validate(raw), self.query, market_evidence, RUN_ID
        )
        self.assertTrue(result.passed, result.errors)

    def test_duration_range_and_stock_code_are_not_claim_values(self):
        evidence = sample_evidence()
        raw = valid_report(evidence)
        raw["claims"][0]["claim"] = (
            "600519未来6-12个月仍有不确定性，区间收益率为19.0%。"
        )
        result = self.validator.validate(
            ResearchReport.model_validate(raw), self.query, evidence, RUN_ID
        )
        self.assertTrue(result.passed, result.errors)

    def test_stock_code_does_not_form_partial_chinese_year(self):
        query = query_spec().model_copy(update={"stock_codes": ["300750"]})
        evidence = sample_evidence(include_report=False)
        evidence[0] = evidence[0].model_copy(update={"subject": "300750"})
        raw = valid_report(evidence)
        raw["subjects"] = ["300750"]
        raw["claims"][0]["claim"] = "300750年化表现存在波动，区间收益率为19.0%。"
        result = self.validator.validate(
            ResearchReport.model_validate(raw), query, evidence, RUN_ID
        )
        self.assertTrue(result.passed, result.errors)

    def test_hundred_million_display_accepts_million_yuan_source(self):
        evidence = sample_evidence()
        evidence[0] = evidence[0].model_copy(
            update={
                "statement": "营业收入为86,044百万元。",
                "data": {
                    **evidence[0].data,
                    "rows": [{"营业收入": "86,044百万元"}],
                    "revenue_million_yuan": 86044,
                },
            }
        )
        raw = valid_report(evidence)
        raw["claims"][0]["claim"] = "贵州茅台营业收入为860.44亿元。"
        result = self.validator.validate(
            ResearchReport.model_validate(raw), self.query, evidence, RUN_ID
        )
        self.assertTrue(result.passed, result.errors)

    def test_shared_decline_direction_applies_to_number_list(self):
        evidence = sample_evidence()
        evidence[0] = evidence[0].model_copy(
            update={
                "statement": "毛利率分别同比-0.8pct/-2.1pct/-2.2pct。",
                "data": {
                    **evidence[0].data,
                    "changes": [-0.8, -2.1, -2.2],
                },
            }
        )
        raw = valid_report(evidence)
        raw["claims"][0]["claim"] = (
            "毛利率分别同比下降0.8、2.1和2.2个百分点。"
        )
        result = self.validator.validate(
            ResearchReport.model_validate(raw), self.query, evidence, RUN_ID
        )
        self.assertTrue(result.passed, result.errors)

    def test_price_range_separator_does_not_make_upper_bound_negative(self):
        evidence = sample_evidence()
        evidence[0] = evidence[0].model_copy(
            update={
                "statement": "52周价格范围1323.69-1634.99元。",
                "data": {
                    **evidence[0].data,
                    "range_low": 1323.69,
                    "range_high": 1634.99,
                },
            }
        )
        raw = valid_report(evidence)
        raw["claims"][0]["claim"] = "52周价格范围1323.69-1634.99元。"
        result = self.validator.validate(
            ResearchReport.model_validate(raw), self.query, evidence, RUN_ID
        )
        self.assertTrue(result.passed, result.errors)

    def test_micro_decline_preserves_negative_direction(self):
        decline_evidence = sample_evidence()
        decline_evidence[0] = decline_evidence[0].model_copy(
            update={
                "statement": "600519营业收入同比下降1.21%。",
                "data": {**decline_evidence[0].data, "revenue_yoy": -0.0121},
            }
        )
        raw = valid_report(decline_evidence)
        raw["claims"][0]["claim"] = "贵州茅台营业收入同比微降1.21%。"
        result = self.validator.validate(
            ResearchReport.model_validate(raw), self.query, decline_evidence, RUN_ID
        )
        self.assertTrue(result.passed, result.errors)

    def test_report_text_decline_direction_matches_claim(self):
        evidence = sample_evidence()
        evidence[0] = evidence[0].model_copy(
            update={
                "statement": "研报显示白酒产量同比下降12.10%。",
                "data": {
                    **evidence[0].data,
                    "text": "国家统计局数据表明白酒产量同比下降12.10%。",
                },
            }
        )
        raw = valid_report(evidence)
        raw["claims"][0]["claim"] = "白酒产量同比下降12.10%。"
        result = self.validator.validate(
            ResearchReport.model_validate(raw), self.query, evidence, RUN_ID
        )
        self.assertTrue(result.passed, result.errors)

    def test_forged_id_wrong_stock_date_and_number_are_rejected(self):
        cases = []
        forged = valid_report(self.evidence)
        forged["claims"][0]["evidence_ids"] = [f"{RUN_ID}:forged"]
        cases.append((forged, "CITATION_UNKNOWN"))
        wrong_stock = valid_report(self.evidence)
        wrong_stock["subjects"] = ["300750"]
        wrong_stock["claims"][0]["claim"] = "宁德时代300750区间收益率为19.0%。"
        cases.append((wrong_stock, "ENTITY_REPORT_SUBJECT_MISMATCH"))
        wrong_date = valid_report(self.evidence)
        wrong_date["data_as_of"] = "2026-07-13"
        cases.append((wrong_date, "DATE_AS_OF_MISMATCH"))
        wrong_number = valid_report(self.evidence)
        wrong_number["claims"][0]["claim"] = "贵州茅台区间收益率为99.0%。"
        cases.append((wrong_number, "NUMERIC_UNSUPPORTED"))
        for raw, expected in cases:
            with self.subTest(expected=expected):
                result = self.validator.validate(
                    ResearchReport.model_validate(raw), self.query, self.evidence, RUN_ID
                )
                self.assertFalse(result.passed)
                self.assertTrue(any(expected in error for error in result.errors), result.errors)

    def test_report_page_and_institution_are_required(self):
        broken_evidence = sample_evidence()
        broken_evidence[1] = broken_evidence[1].model_copy(
            update={
                "data": {**broken_evidence[1].data, "page_number": None},
                "source": broken_evidence[1].source.model_copy(update={"metadata": {}}),
            }
        )
        raw = valid_report(broken_evidence)
        raw["claims"][1]["claim"] = "研报指出公司正在推进直营渠道改革。"
        result = self.validator.validate(
            ResearchReport.model_validate(raw), self.query, broken_evidence, RUN_ID
        )
        self.assertTrue(any("REPORT_PAGE_MISSING" in error for error in result.errors))
        self.assertTrue(any("REPORT_ATTRIBUTION_MISSING" in error for error in result.errors))

    def test_institution_view_without_report_evidence_is_rejected(self):
        evidence = sample_evidence(include_report=False)
        raw = valid_report(evidence)
        raw["claims"][0]["claim"] = "机构认为贵州茅台区间表现稳健。"
        result = self.validator.validate(
            ResearchReport.model_validate(raw), self.query, evidence, RUN_ID
        )
        self.assertTrue(any("REPORT_EVIDENCE_ABSENT" in error for error in result.errors))

    def test_summary_and_risk_require_current_run_evidence(self):
        raw = valid_report(self.evidence)
        raw["summary_evidence_ids"] = ["other-run:forged"]
        raw["risks"][0]["evidence_ids"] = []
        result = self.validator.validate(
            ResearchReport.model_validate(raw), self.query, self.evidence, RUN_ID
        )
        self.assertFalse(result.passed)
        self.assertTrue(
            any("summary:CITATION_UNKNOWN" in item for item in result.errors)
        )
        self.assertIn("risk[0]:CITATION_MISSING", result.errors)

    def test_calculation_risk_requires_calculation_evidence(self):
        raw = valid_report(self.evidence)
        raw["risks"][0] = {
            "risk": "渠道改革效果存在不确定性。",
            "classification": "calculation",
            "evidence_ids": [self.evidence[1].evidence_id],
            "confidence": "medium",
        }
        result = self.validator.validate(
            ResearchReport.model_validate(raw), self.query, self.evidence, RUN_ID
        )
        self.assertIn(
            "risk[0]:CALCULATION_EVIDENCE_REQUIRED", result.errors
        )


class ReportingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_data_as_of_is_bound_from_evidence_not_model_guess(self):
        evidence = sample_evidence()
        guessed = valid_report(evidence)
        guessed["data_as_of"] = "2026-07-15"
        provider = SequenceProvider([guessed])
        settings = Settings(max_report_revisions=0)
        result = await ReportingService(
            settings, EvidenceOnlyReporter(settings, provider)
        ).run("综合分析", query_spec(), evidence, RUN_ID)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.report.data_as_of, date(2026, 7, 14))
        self.assertEqual(provider.calls, 1)

    async def test_one_revision_can_repair_report(self):
        evidence = sample_evidence()
        invalid = valid_report(evidence)
        invalid["claims"][0]["claim"] = "贵州茅台区间收益率为99.0%。"
        provider = SequenceProvider([invalid, valid_report(evidence)])
        service = ReportingService(
            Settings(max_report_revisions=1),
            EvidenceOnlyReporter(Settings(), provider),
        )
        result = await service.run("综合分析", query_spec(), evidence, RUN_ID)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(provider.calls, 2)
        self.assertTrue(provider.feedback[1])

    async def test_second_invalid_report_stops(self):
        evidence = sample_evidence()
        invalid = valid_report(evidence)
        invalid["claims"][0]["claim"] = "贵州茅台区间收益率为99.0%。"
        provider = SequenceProvider([invalid, invalid, valid_report(evidence)])
        settings = Settings(max_report_revisions=1)
        result = await ReportingService(
            settings, EvidenceOnlyReporter(settings, provider)
        ).run("综合分析", query_spec(), evidence, RUN_ID)
        self.assertEqual(result.status, "validation_failed")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(provider.calls, 2)

    async def test_no_evidence_or_provider_failure_is_not_templated(self):
        provider = SequenceProvider([valid_report(sample_evidence())])
        settings = Settings()
        result = await ReportingService(
            settings, EvidenceOnlyReporter(settings, provider)
        ).run("综合分析", query_spec(), [], RUN_ID)
        self.assertEqual(result.status, "generation_failed")
        self.assertIsNone(result.report)


if __name__ == "__main__":
    unittest.main()
