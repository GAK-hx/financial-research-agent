import unittest
from datetime import date, datetime, timezone

import pandas as pd
from pydantic import ValidationError

from financial_research_agent.risk.models import (
    BenchmarkSplit,
    DataAvailability,
    DisclosureEventType,
    EvidencePointer,
    IssuerRiskCase,
    PointInTimeBoundary,
    RiskCategory,
    RiskFact,
    RiskLabel,
    RiskStatus,
)
from financial_research_agent.risk.pit import select_visible_facts
from financial_research_agent.risk.pools import load_correctness_pool
from financial_research_agent.risk.normalize import normalize_eastmoney_statement
from financial_research_agent.risk.disclosures import (
    classify_title,
    clean_title,
    normalize_disclosures,
)
from financial_research_agent.risk.document_audit import _direct_pdf_url
from financial_research_agent.risk.finqa_tools import (
    canonicalize_finqa_program,
    execute_finqa_program,
)
from financial_research_agent.risk.registry import RiskMetricRegistry
from financial_research_agent.risk.schema import DWD_FACT_SCHEMA, TABLE_SCHEMAS

UTC = timezone.utc
HASH_A = "a" * 64
HASH_B = "b" * 64


def fact(
    *,
    value: float,
    published_at: datetime,
    observed_at: datetime,
    revision_no: int,
    digest: str = HASH_A,
) -> RiskFact:
    return RiskFact(
        issuer_id="600519",
        report_period=date(2025, 12, 31),
        metric_code="current_assets",
        value=value,
        unit="CNY",
        currency="CNY",
        availability=DataAvailability.PRESENT,
        source_name="fixture",
        source_record_id=f"record-{revision_no}-{digest[0]}",
        source_published_at=published_at,
        observed_at=observed_at,
        revision_no=revision_no,
        snapshot_id=revision_no + 1,
        content_sha256=digest,
    )


class RiskFoundationTests(unittest.TestCase):
    def test_finqa_nested_program_compiles_to_controlled_sequence(self) -> None:
        nested = "add(1654, subtract(1654, 1251))"

        canonical = canonicalize_finqa_program(nested)
        result = execute_finqa_program(canonical, [])

        self.assertEqual(canonical, "subtract(1654, 1251), add(1654, #0)")
        self.assertTrue(result.valid)
        self.assertEqual(result.value, 2057.0)
        self.assertEqual(result.steps_executed, 2)

    def test_finqa_multiple_nested_arguments_preserve_dependency_order(self) -> None:
        nested = "divide(subtract(469, 77), subtract(920, 95))"

        canonical = canonicalize_finqa_program(nested)
        result = execute_finqa_program(canonical, [])

        self.assertEqual(
            canonical,
            "subtract(469, 77), subtract(920, 95), divide(#0, #1)",
        )
        self.assertTrue(result.valid)
        self.assertEqual(result.value, 0.47515)

    def test_cninfo_detail_url_maps_to_disclosure_date_pdf(self) -> None:
        event = {
            "url": (
                "http://www.cninfo.com.cn/new/disclosure/detail?stockCode=000002&"
                "announcementId=1204519141&announcementTime=2018-03-27"
            ),
            "published_at": datetime(2018, 3, 26, 16, tzinfo=timezone.utc),
        }

        self.assertEqual(
            _direct_pdf_url(event),
            "https://static.cninfo.com.cn/finalpage/2018-03-27/1204519141.PDF",
        )

    def test_default_registry_is_versioned_and_covers_four_categories(self) -> None:
        registry = RiskMetricRegistry.load_default()
        definitions = registry.all()
        self.assertEqual(len(definitions), 13)
        self.assertEqual({item.category for item in definitions}, set(RiskCategory))
        self.assertEqual(registry.get("current_ratio").unit, "ratio")
        self.assertEqual(
            len(registry.by_category(RiskCategory.DISCLOSURE_AUDIT)),
            3,
        )

    def test_correctness_pool_is_frozen_before_source_audit(self) -> None:
        pool = load_correctness_pool()
        self.assertEqual(len(pool.entries), 20)
        self.assertEqual(len({item.issuer_id for item in pool.entries}), 20)
        self.assertEqual(
            sum(not item.generic_ratio_applicable for item in pool.entries),
            2,
        )

    def test_point_in_time_selects_latest_revision_visible_on_both_clocks(self) -> None:
        boundary = PointInTimeBoundary(
            as_of_date=date(2026, 1, 31),
            system_cutoff=datetime(2026, 1, 31, 23, 59, tzinfo=UTC),
            data_snapshot_id="fixture-snapshot-1",
        )
        facts = [
            fact(
                value=100.0,
                published_at=datetime(2026, 1, 10, tzinfo=UTC),
                observed_at=datetime(2026, 1, 11, tzinfo=UTC),
                revision_no=0,
            ),
            fact(
                value=110.0,
                published_at=datetime(2026, 1, 20, tzinfo=UTC),
                observed_at=datetime(2026, 1, 21, tzinfo=UTC),
                revision_no=1,
                digest=HASH_B,
            ),
            fact(
                value=120.0,
                published_at=datetime(2026, 2, 1, tzinfo=UTC),
                observed_at=datetime(2026, 2, 1, 1, tzinfo=UTC),
                revision_no=2,
            ),
            fact(
                value=115.0,
                published_at=datetime(2026, 1, 25, tzinfo=UTC),
                observed_at=datetime(2026, 2, 2, tzinfo=UTC),
                revision_no=2,
            ),
        ]
        visible = select_visible_facts(facts, boundary)
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0].value, 110.0)
        self.assertEqual(visible[0].revision_no, 1)

    def test_unavailable_fact_cannot_silently_carry_zero(self) -> None:
        with self.assertRaises(ValidationError):
            RiskFact(
                issuer_id="600519",
                report_period=date(2025, 12, 31),
                metric_code="goodwill",
                value=0.0,
                unit="CNY",
                currency="CNY",
                availability=DataAvailability.NOT_AVAILABLE_FROM_SOURCE,
                source_name="fixture",
                source_record_id="missing-goodwill",
                source_published_at=datetime(2026, 1, 10, tzinfo=UTC),
                observed_at=datetime(2026, 1, 11, tzinfo=UTC),
                content_sha256=HASH_A,
            )

    def test_benchmark_case_keeps_outcome_after_cutoff(self) -> None:
        boundary = PointInTimeBoundary(
            as_of_date=date(2026, 1, 31),
            system_cutoff=datetime(2026, 2, 10, tzinfo=UTC),
            data_snapshot_id="fixture-snapshot-1",
        )
        evidence = EvidencePointer(
            evidence_id="evidence:annual-report:1",
            source_name="fixture",
            source_record_id="annual-report-2025",
            content_sha256=HASH_A,
            published_at=datetime(2026, 1, 20, tzinfo=UTC),
            locator="fixture.pdf#page=10",
        )
        case = IssuerRiskCase(
            case_id="irb-0001",
            dataset_version="issuer-risk-bench-v1",
            split=BenchmarkSplit.DEVELOPMENT,
            issuer_id="600519",
            report_period=date(2025, 12, 31),
            boundary=boundary,
            task_type="risk_detection",
            question="截至分析日是否存在需要升级复核的流动性风险？",
            gold_label=RiskLabel(
                status=RiskStatus.ESCALATE,
                categories=[RiskCategory.LIQUIDITY],
                outcome_date=date(2026, 3, 1),
                outcome_type="debt_overdue",
                evidence_ids=[evidence.evidence_id],
                annotator_id="fixture-a",
            ),
            evidence=[evidence],
        )
        self.assertEqual(case.gold_label.outcome_date, date(2026, 3, 1))
        invalid_payload = case.model_dump()
        invalid_payload["gold_label"]["outcome_date"] = date(2026, 1, 30)
        with self.assertRaises(ValidationError):
            IssuerRiskCase.model_validate(invalid_payload)

    def test_iceberg_foundation_schemas_are_explicit(self) -> None:
        self.assertEqual(len(TABLE_SCHEMAS), 6)
        self.assertTrue(DWD_FACT_SCHEMA.find_field("source_published_at").required)
        self.assertTrue(DWD_FACT_SCHEMA.find_field("observed_at").required)
        self.assertTrue(DWD_FACT_SCHEMA.find_field("availability").required)

    def test_eastmoney_normalizer_uses_later_update_date_conservatively(self) -> None:
        raw = pd.DataFrame(
            [
                {
                    "SECURITY_CODE": "600519",
                    "REPORT_DATE": "2025-12-31",
                    "NOTICE_DATE": "2026-04-01",
                    "UPDATE_DATE": "2026-08-15",
                    "CURRENCY": "CNY",
                    "OPERATE_INCOME": 100.0,
                    "TOTAL_OPERATE_INCOME": 100.0,
                    "PARENT_NETPROFIT": 20.0,
                    "FE_INTEREST_EXPENSE": None,
                    "ASSET_IMPAIRMENT_LOSS": 2.0,
                    "CREDIT_IMPAIRMENT_LOSS": None,
                    "OPINION_TYPE": "标准无保留意见",
                }
            ]
        )
        observed_at = datetime(2026, 9, 1, tzinfo=UTC)
        facts, rejected = normalize_eastmoney_statement(
            raw,
            "income",
            observed_at=observed_at,
        )
        self.assertEqual(rejected, [])
        by_code = {item.metric_code: item for item in facts}
        self.assertEqual(
            by_code["revenue"].source_published_at,
            datetime(2026, 8, 14, 16, tzinfo=UTC),
        )
        self.assertEqual(by_code["revenue"].value, 100.0)
        self.assertEqual(
            by_code["interest_expense"].availability,
            DataAvailability.NOT_DISCLOSED,
        )
        self.assertEqual(by_code["audit_opinion_flag"].value, 0.0)

    def test_eastmoney_normalizer_rejects_future_source_update(self) -> None:
        raw = pd.DataFrame(
            [
                {
                    "SECURITY_CODE": "600519",
                    "REPORT_DATE": "2025-12-31",
                    "NOTICE_DATE": "2026-04-01",
                    "UPDATE_DATE": "2026-10-01",
                }
            ]
        )
        facts, rejected = normalize_eastmoney_statement(
            raw,
            "balance",
            observed_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
        self.assertEqual(facts, [])
        self.assertEqual(rejected[0]["reason"], "source_update_after_observation")

    def test_disclosure_normalizer_deduplicates_queries_and_keeps_tags(self) -> None:
        row = {
            "代码": "600519",
            "简称": "贵州茅台",
            "公告标题": "关于前期会计差错更正的公告",
            "公告时间": "2026-04-01",
            "公告链接": "http://www.cninfo.com.cn/example.pdf",
        }
        events, rejected = normalize_disclosures(
            {
                "correction": pd.DataFrame([row]),
                "inquiry": pd.DataFrame([row]),
            },
            observed_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
        self.assertEqual(rejected, [])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].query_tags, ["correction", "inquiry"])
        self.assertIn(DisclosureEventType.FINANCIAL_RESTATEMENT, events[0].event_types)
        self.assertTrue(events[0].requires_document_review)

    def test_disclosure_title_classification_is_candidate_only(self) -> None:
        types = classify_title("收到交易所问询函暨风险提示公告")
        self.assertIn(DisclosureEventType.REGULATORY_INQUIRY, types)
        self.assertEqual(classify_title("关于董事会会议的公告"), [DisclosureEventType.OTHER])

    def test_disclosure_title_removes_cninfo_highlight_html(self) -> None:
        title = "关于年报<em>问询</em><em>函</em>回复的公告"
        self.assertEqual(clean_title(title), "关于年报问询函回复的公告")
        self.assertIn(DisclosureEventType.REGULATORY_INQUIRY, classify_title(title))


if __name__ == "__main__":
    unittest.main()
