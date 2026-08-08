from pyiceberg.schema import Schema
from pyiceberg.types import DateType, DoubleType, NestedField, StringType, TimestamptzType

INCOME_TABLE = "financial.income_statement"
BALANCE_TABLE = "financial.balance_sheet"
CASH_FLOW_TABLE = "financial.cash_flow"
METRICS_TABLE = "financial.metrics"


def _metadata_fields(start_id: int = 1) -> list[NestedField]:
    return [
        NestedField(start_id, "stock_code", StringType(), required=False),
        NestedField(start_id + 1, "report_date", DateType(), required=False),
        NestedField(start_id + 2, "announcement_date", DateType(), required=False),
        NestedField(start_id + 3, "currency", StringType(), required=False),
        NestedField(start_id + 4, "statement_scope", StringType(), required=False),
    ]


INCOME_SCHEMA = Schema(
    *_metadata_fields(),
    NestedField(6, "revenue", DoubleType(), required=False),
    NestedField(7, "operating_cost", DoubleType(), required=False),
    NestedField(8, "parent_net_profit", DoubleType(), required=False),
    NestedField(9, "source", StringType(), required=False),
    NestedField(10, "batch_id", StringType(), required=False),
    NestedField(11, "ingested_at", TimestamptzType(), required=False),
)

BALANCE_SCHEMA = Schema(
    *_metadata_fields(),
    NestedField(6, "total_assets", DoubleType(), required=False),
    NestedField(7, "total_liabilities", DoubleType(), required=False),
    NestedField(8, "parent_equity", DoubleType(), required=False),
    NestedField(9, "source", StringType(), required=False),
    NestedField(10, "batch_id", StringType(), required=False),
    NestedField(11, "ingested_at", TimestamptzType(), required=False),
)

CASH_FLOW_SCHEMA = Schema(
    *_metadata_fields(),
    NestedField(6, "operating_cash_flow", DoubleType(), required=False),
    NestedField(7, "source", StringType(), required=False),
    NestedField(8, "batch_id", StringType(), required=False),
    NestedField(9, "ingested_at", TimestamptzType(), required=False),
)

METRICS_SCHEMA = Schema(
    *_metadata_fields(),
    NestedField(6, "revenue", DoubleType(), required=False),
    NestedField(7, "parent_net_profit", DoubleType(), required=False),
    NestedField(8, "operating_cash_flow", DoubleType(), required=False),
    NestedField(9, "revenue_yoy", DoubleType(), required=False),
    NestedField(10, "parent_net_profit_yoy", DoubleType(), required=False),
    NestedField(11, "gross_margin", DoubleType(), required=False),
    NestedField(12, "debt_ratio", DoubleType(), required=False),
    NestedField(13, "roe_period", DoubleType(), required=False),
    NestedField(14, "formula_version", StringType(), required=False),
    NestedField(15, "source", StringType(), required=False),
    NestedField(16, "batch_id", StringType(), required=False),
    NestedField(17, "ingested_at", TimestamptzType(), required=False),
)

TABLE_SCHEMAS = {
    INCOME_TABLE: INCOME_SCHEMA,
    BALANCE_TABLE: BALANCE_SCHEMA,
    CASH_FLOW_TABLE: CASH_FLOW_SCHEMA,
    METRICS_TABLE: METRICS_SCHEMA,
}
