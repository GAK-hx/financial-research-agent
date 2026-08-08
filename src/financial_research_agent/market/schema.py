from pyiceberg.schema import Schema
from pyiceberg.types import DateType, DoubleType, LongType, NestedField, StringType, TimestamptzType

KLINE_DAILY_TABLE = "market.kline_daily"
BUSINESS_KEY = ["stock_code", "trade_date", "adjust_type"]

KLINE_DAILY_SCHEMA = Schema(
    NestedField(1, "stock_code", StringType(), required=False),
    NestedField(2, "trade_date", DateType(), required=False),
    NestedField(3, "open", DoubleType(), required=False),
    NestedField(4, "high", DoubleType(), required=False),
    NestedField(5, "low", DoubleType(), required=False),
    NestedField(6, "close", DoubleType(), required=False),
    NestedField(7, "volume", LongType(), required=False),
    NestedField(8, "amount", DoubleType(), required=False),
    NestedField(9, "amplitude", DoubleType(), required=False),
    NestedField(10, "pct_change", DoubleType(), required=False),
    NestedField(11, "change", DoubleType(), required=False),
    NestedField(12, "turnover_rate", DoubleType(), required=False),
    NestedField(13, "adjust_type", StringType(), required=False),
    NestedField(14, "source", StringType(), required=False),
    NestedField(15, "batch_id", StringType(), required=False),
    NestedField(16, "ingested_at", TimestamptzType(), required=False),
)
