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

SECURITY_MASTER_TABLE = "metadata.security_master"
UNIVERSE_MEMBERSHIP_TABLE = "metadata.universe_membership"
FACTOR_VALUES_TABLE = "financial.factor_values"
FACTOR_RUNS_TABLE = "metadata.factor_runs"

SECURITY_MASTER_SCHEMA = Schema(
    NestedField(1, "stock_code", StringType(), required=False),
    NestedField(2, "display_name", StringType(), required=False),
    NestedField(3, "exchange", StringType(), required=False),
    NestedField(4, "asset_type", StringType(), required=False),
    NestedField(5, "effective_date", DateType(), required=False),
    NestedField(6, "version", StringType(), required=False),
    NestedField(7, "loaded_at", TimestamptzType(), required=False),
)

UNIVERSE_MEMBERSHIP_SCHEMA = Schema(
    NestedField(1, "universe_id", StringType(), required=False),
    NestedField(2, "universe_version", StringType(), required=False),
    NestedField(3, "effective_date", DateType(), required=False),
    NestedField(4, "stock_code", StringType(), required=False),
    NestedField(5, "selection_policy", StringType(), required=False),
    NestedField(6, "loaded_at", TimestamptzType(), required=False),
)

FACTOR_VALUES_SCHEMA = Schema(
    NestedField(1, "run_id", StringType(), required=False),
    NestedField(2, "stock_code", StringType(), required=False),
    NestedField(3, "as_of_date", DateType(), required=False),
    NestedField(4, "available_at", TimestamptzType(), required=False),
    NestedField(5, "universe_id", StringType(), required=False),
    NestedField(6, "universe_version", StringType(), required=False),
    NestedField(7, "factor_name", StringType(), required=False),
    NestedField(8, "factor_value", DoubleType(), required=False),
    NestedField(9, "percentile_rank", DoubleType(), required=False),
    NestedField(10, "coverage_count", IntegerType(), required=False),
    NestedField(11, "registry_version", StringType(), required=False),
    NestedField(12, "formula_version", StringType(), required=False),
    NestedField(13, "input_snapshot_id", LongType(), required=False),
    NestedField(14, "status", StringType(), required=False),
    NestedField(15, "missing_reason", StringType(), required=False),
    NestedField(16, "point_in_time_eligible", BooleanType(), required=False),
    NestedField(17, "computed_at", TimestamptzType(), required=False),
)

FACTOR_RUNS_SCHEMA = Schema(
    NestedField(1, "run_id", StringType(), required=False),
    NestedField(2, "universe_id", StringType(), required=False),
    NestedField(3, "universe_version", StringType(), required=False),
    NestedField(4, "as_of_date", DateType(), required=False),
    NestedField(5, "registry_version", StringType(), required=False),
    NestedField(6, "market_snapshot_id", LongType(), required=False),
    NestedField(7, "financial_snapshot_id", LongType(), required=False),
    NestedField(8, "universe_size", IntegerType(), required=False),
    NestedField(9, "covered_stocks", IntegerType(), required=False),
    NestedField(10, "factor_rows", IntegerType(), required=False),
    NestedField(11, "engine", StringType(), required=False),
    NestedField(12, "status", StringType(), required=False),
    NestedField(13, "started_at", TimestamptzType(), required=False),
    NestedField(14, "finished_at", TimestamptzType(), required=False),
)

TABLE_SCHEMAS = {
    SECURITY_MASTER_TABLE: SECURITY_MASTER_SCHEMA,
    UNIVERSE_MEMBERSHIP_TABLE: UNIVERSE_MEMBERSHIP_SCHEMA,
    FACTOR_VALUES_TABLE: FACTOR_VALUES_SCHEMA,
    FACTOR_RUNS_TABLE: FACTOR_RUNS_SCHEMA,
}
