import json
from pathlib import Path

import pyarrow.parquet as pq

from financial_research_agent.config import get_settings
from financial_research_agent.market.normalize import normalize_daily_market
from financial_research_agent.market.schema import BUSINESS_KEY, KLINE_DAILY_TABLE
from financial_research_agent.repositories.iceberg import IcebergRepository

COMPARE_FIELDS = [
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "amplitude",
    "pct_change",
    "change",
    "turnover_rate",
]


def main() -> None:
    settings = get_settings()
    frame = IcebergRepository(settings).scan(KLINE_DAILY_TABLE).to_pandas()
    result = {
        "table": KLINE_DAILY_TABLE,
        "total_rows": len(frame),
        "duplicate_business_keys": int(frame.duplicated(BUSINESS_KEY).sum()),
        "invalid_ohlc_rows": int(
            (
                (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
                | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
            ).sum()
        ),
        "stocks": [],
        "sample_matches": 0,
        "sample_total": 0,
    }
    for symbol in settings.stock_codes:
        stock = frame.loc[frame["stock_code"] == symbol].sort_values("trade_date")
        raw_root = Path(settings.lake_root) / "raw" / f"market_daily_{symbol}"
        latest_raw = sorted(raw_root.glob("batch_id=*/part-00000.parquet"))[-1]
        raw = pq.ParquetFile(latest_raw).read().to_pandas()
        normalized, _, _ = normalize_daily_market(raw, symbol, "qfq", "akshare", "audit")
        sample = normalized.head(5)
        curated_sample = stock.merge(sample[BUSINESS_KEY], on=BUSINESS_KEY, how="inner")
        normalized_sample = sample.merge(curated_sample[BUSINESS_KEY], on=BUSINESS_KEY, how="inner")
        for (_, curated), (_, source) in zip(
            curated_sample.sort_values("trade_date").iterrows(),
            normalized_sample.sort_values("trade_date").iterrows(),
        ):
            result["sample_total"] += 1
            if all(curated[field] == source[field] for field in COMPARE_FIELDS):
                result["sample_matches"] += 1
        result["stocks"].append(
            {
                "stock_code": symbol,
                "rows": len(stock),
                "min_trade_date": str(stock["trade_date"].min()),
                "max_trade_date": str(stock["trade_date"].max()),
            }
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if (
        result["duplicate_business_keys"]
        or result["invalid_ohlc_rows"]
        or result["sample_matches"] != result["sample_total"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
