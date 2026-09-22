from pyiceberg.schema import Schema
from pyiceberg.types import (
    BooleanType,
    DateType,
    DoubleType,
    IntegerType,
    LongType,
    NestedField,
    StringType,
    TimestamptzType,
)

DWD_FACT_TABLE = "financial.risk_fact_pit"
DISCLOSURE_EVENT_TABLE = "financial.disclosure_event"
DWS_FEATURE_TABLE = "financial.risk_feature_pit"
ADS_CANDIDATE_TABLE = "financial.risk_candidate"
LABEL_TABLE = "metadata.risk_label"
BENCHMARK_CASE_TABLE = "metadata.issuer_risk_bench_case"

DWD_FACT_SCHEMA = Schema(
    NestedField(1, "issuer_id", StringType(), required=True),
    NestedField(2, "report_period", DateType(), required=True),
    NestedField(3, "metric_code", StringType(), required=True),
    NestedField(4, "value", DoubleType(), required=False),
    NestedField(5, "unit", StringType(), required=True),
    NestedField(6, "currency", StringType(), required=False),
    NestedField(7, "availability", StringType(), required=True),
    NestedField(8, "source_name", StringType(), required=True),
    NestedField(9, "source_record_id", StringType(), required=True),
    NestedField(10, "source_published_at", TimestamptzType(), required=True),
    NestedField(11, "observed_at", TimestamptzType(), required=True),
    NestedField(12, "revision_no", IntegerType(), required=True),
    NestedField(13, "source_snapshot_id", LongType(), required=False),
    NestedField(14, "content_sha256", StringType(), required=True),
    NestedField(15, "mapping_version", StringType(), required=True),
    NestedField(16, "quality_passed", BooleanType(), required=True),
)

DISCLOSURE_EVENT_SCHEMA = Schema(
    NestedField(1, "event_id", StringType(), required=True),
    NestedField(2, "issuer_id", StringType(), required=True),
    NestedField(3, "issuer_name", StringType(), required=True),
    NestedField(4, "title", StringType(), required=True),
    NestedField(5, "published_at", TimestamptzType(), required=True),
    NestedField(6, "url", StringType(), required=True),
    NestedField(7, "source_name", StringType(), required=True),
    NestedField(8, "source_record_id", StringType(), required=True),
    NestedField(9, "content_sha256", StringType(), required=True),
    NestedField(10, "query_tags_json", StringType(), required=True),
    NestedField(11, "event_types_json", StringType(), required=True),
    NestedField(12, "requires_document_review", BooleanType(), required=True),
    NestedField(13, "observed_at", TimestamptzType(), required=True),
)

DWS_FEATURE_SCHEMA = Schema(
    NestedField(1, "issuer_id", StringType(), required=True),
    NestedField(2, "report_period", DateType(), required=True),
    NestedField(3, "as_of_date", DateType(), required=True),
    NestedField(4, "data_snapshot_id", StringType(), required=True),
    NestedField(5, "metric_code", StringType(), required=True),
    NestedField(6, "metric_version", StringType(), required=True),
    NestedField(7, "value", DoubleType(), required=False),
    NestedField(8, "unit", StringType(), required=True),
    NestedField(9, "availability", StringType(), required=True),
    NestedField(10, "periods_used", IntegerType(), required=True),
    NestedField(11, "source_fact_ids_json", StringType(), required=True),
    NestedField(12, "computed_at", TimestamptzType(), required=True),
)

ADS_CANDIDATE_SCHEMA = Schema(
    NestedField(1, "candidate_id", StringType(), required=True),
    NestedField(2, "issuer_id", StringType(), required=True),
    NestedField(3, "report_period", DateType(), required=True),
    NestedField(4, "as_of_date", DateType(), required=True),
    NestedField(5, "data_snapshot_id", StringType(), required=True),
    NestedField(6, "risk_category", StringType(), required=True),
    NestedField(7, "status", StringType(), required=True),
    NestedField(8, "rule_score", DoubleType(), required=False),
    NestedField(9, "triggered_metrics_json", StringType(), required=True),
    NestedField(10, "evidence_ids_json", StringType(), required=True),
    NestedField(11, "created_at", TimestamptzType(), required=True),
)

LABEL_SCHEMA = Schema(
    NestedField(1, "case_id", StringType(), required=True),
    NestedField(2, "annotator_id", StringType(), required=True),
    NestedField(3, "status", StringType(), required=True),
    NestedField(4, "categories_json", StringType(), required=True),
    NestedField(5, "outcome_date", DateType(), required=False),
    NestedField(6, "outcome_type", StringType(), required=False),
    NestedField(7, "evidence_ids_json", StringType(), required=True),
    NestedField(8, "rationale", StringType(), required=True),
    NestedField(9, "label_version", StringType(), required=True),
    NestedField(10, "created_at", TimestamptzType(), required=True),
)

BENCHMARK_CASE_SCHEMA = Schema(
    NestedField(1, "case_id", StringType(), required=True),
    NestedField(2, "dataset_version", StringType(), required=True),
    NestedField(3, "split", StringType(), required=True),
    NestedField(4, "issuer_id", StringType(), required=True),
    NestedField(5, "report_period", DateType(), required=True),
    NestedField(6, "as_of_date", DateType(), required=True),
    NestedField(7, "system_cutoff", TimestamptzType(), required=True),
    NestedField(8, "data_snapshot_id", StringType(), required=True),
    NestedField(9, "task_type", StringType(), required=True),
    NestedField(10, "question", StringType(), required=True),
    NestedField(11, "gold_label_json", StringType(), required=False),
    NestedField(12, "evidence_json", StringType(), required=True),
    NestedField(13, "expected_answer_json", StringType(), required=True),
    NestedField(14, "annotation_status", StringType(), required=True),
)

TABLE_SCHEMAS = {
    DWD_FACT_TABLE: DWD_FACT_SCHEMA,
    DISCLOSURE_EVENT_TABLE: DISCLOSURE_EVENT_SCHEMA,
    DWS_FEATURE_TABLE: DWS_FEATURE_SCHEMA,
    ADS_CANDIDATE_TABLE: ADS_CANDIDATE_SCHEMA,
    LABEL_TABLE: LABEL_SCHEMA,
    BENCHMARK_CASE_TABLE: BENCHMARK_CASE_SCHEMA,
}
