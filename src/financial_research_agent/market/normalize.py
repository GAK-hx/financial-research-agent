from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from financial_research_agent.data_management.models import (
    DataQualityResult,
    QualityIssue,
    QualitySeverity,
)

FIELD_MAP = {
    "日期": "trade_date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude",
    "涨跌幅": "pct_change",
    "涨跌额": "change",
    "换手率": "turnover_rate",
}
REQUIRED_SOURCE_FIELDS = frozenset(FIELD_MAP)
PRICE_FIELDS = ["open", "high", "low", "close"]
NON_NEGATIVE_FIELDS = [*PRICE_FIELDS, "volume", "amount", "turnover_rate"]


def normalize_daily_market(
    raw: pd.DataFrame,
    stock_code: str,
    adjust_type: str,
    source: str,
    batch_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame, DataQualityResult]:
    missing = REQUIRED_SOURCE_FIELDS.difference(raw.columns)
    if missing:
        raise ValueError(f"source fields missing: {', '.join(sorted(missing))}")
    frame = raw.rename(columns=FIELD_MAP)[list(FIELD_MAP.values())].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce").dt.date
    for field in [*PRICE_FIELDS, "amount", "amplitude", "pct_change", "change", "turnover_rate"]:
        frame[field] = pd.to_numeric(frame[field], errors="coerce").astype("float64")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce").astype("Int64")
    frame.insert(0, "stock_code", stock_code)
    frame["adjust_type"] = adjust_type
    frame["source"] = source
    frame["batch_id"] = batch_id
    frame["ingested_at"] = datetime.now(timezone.utc)

    reasons: dict[int, list[str]] = {}
    for index, row in frame.iterrows():
        row_reasons: list[str] = []
        if len(stock_code) != 6 or not stock_code.isdigit():
            row_reasons.append("invalid_stock_code")
        if adjust_type != "qfq":
            row_reasons.append("unsupported_adjust_type")
        if pd.isna(row["trade_date"]):
            row_reasons.append("invalid_trade_date")
        if any(pd.isna(row[field]) for field in NON_NEGATIVE_FIELDS):
            row_reasons.append("missing_required_numeric")
        elif any(row[field] < 0 for field in NON_NEGATIVE_FIELDS):
            row_reasons.append("negative_value")
        elif row["high"] < max(row["open"], row["close"], row["low"]):
            row_reasons.append("invalid_high")
        elif row["low"] > min(row["open"], row["close"], row["high"]):
            row_reasons.append("invalid_low")
        if row_reasons:
            reasons[index] = row_reasons

    duplicate_mask = frame.duplicated(["stock_code", "trade_date", "adjust_type"], keep="first")
    for index in frame.index[duplicate_mask]:
        reasons.setdefault(index, []).append("duplicate_business_key")

    rejected_indexes = set(reasons)
    accepted = frame.loc[~frame.index.isin(rejected_indexes)].reset_index(drop=True)
    rejected = frame.loc[frame.index.isin(rejected_indexes)].copy()
    if not rejected.empty:
        rejected["rejection_reasons"] = ["|".join(reasons[index]) for index in rejected.index]
        rejected = rejected.reset_index(drop=True)
    issues = [
        QualityIssue(
            rule="daily_market_row_validation",
            severity=QualitySeverity.ERROR,
            message="|".join(row_reasons),
            row_number=int(index),
        )
        for index, row_reasons in reasons.items()
    ]
    result = DataQualityResult(
        checked_rows=len(frame),
        accepted_rows=len(accepted),
        rejected_rows=len(rejected),
        issues=issues,
    )
    return accepted, rejected, result
