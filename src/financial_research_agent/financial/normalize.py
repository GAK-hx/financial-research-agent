from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

FORMULA_VERSION = "financial_metrics_v1"

COMMON_MAP = {
    "报告日": "report_date",
    "公告日期": "announcement_date",
    "币种": "currency",
    "类型": "statement_scope",
}
STATEMENT_MAPS = {
    "income": {
        **COMMON_MAP,
        "营业收入": "revenue",
        "营业成本": "operating_cost",
        "归属于母公司所有者的净利润": "parent_net_profit",
    },
    "balance": {
        **COMMON_MAP,
        "资产总计": "total_assets",
        "负债合计": "total_liabilities",
        "归属于母公司股东权益合计": "parent_equity",
    },
    "cash_flow": {
        **COMMON_MAP,
        "经营活动产生的现金流量净额": "operating_cash_flow",
    },
}


def normalize_statement(
    raw: pd.DataFrame,
    statement: str,
    stock_code: str,
    source: str,
    batch_id: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    mapping = STATEMENT_MAPS[statement]
    missing = set(mapping).difference(raw.columns)
    if missing:
        raise ValueError(f"{statement} source fields missing: {', '.join(sorted(missing))}")
    frame = raw.rename(columns=mapping)[list(mapping.values())].copy()
    frame["report_date"] = pd.to_datetime(frame["report_date"], format="%Y%m%d", errors="coerce").dt.date
    frame["announcement_date"] = pd.to_datetime(
        frame["announcement_date"], format="%Y%m%d", errors="coerce"
    ).dt.date
    numeric_fields = [field for field in mapping.values() if field not in COMMON_MAP.values()]
    for field in numeric_fields:
        frame[field] = pd.to_numeric(frame[field], errors="coerce").astype("float64")
    frame.insert(0, "stock_code", stock_code)
    frame["source"] = source
    frame["batch_id"] = batch_id
    frame["ingested_at"] = datetime.now(timezone.utc)

    invalid = frame["report_date"].isna() | frame.duplicated(
        ["stock_code", "report_date"], keep="first"
    )
    essential = numeric_fields[0]
    invalid |= frame[essential].isna()
    rejected = frame.loc[invalid].copy()
    if not rejected.empty:
        rejected["rejection_reason"] = "invalid_key_duplicate_or_missing_essential_value"
    accepted = frame.loc[~invalid].sort_values("report_date").reset_index(drop=True)
    return accepted, rejected.reset_index(drop=True)


def calculate_metrics(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    cash_flow: pd.DataFrame,
    batch_id: str,
    source: str,
) -> pd.DataFrame:
    common = ["stock_code", "report_date"]
    frame = income.merge(
        balance[common + ["total_assets", "total_liabilities", "parent_equity"]],
        on=common,
        how="left",
    ).merge(
        cash_flow[common + ["operating_cash_flow"]],
        on=common,
        how="left",
    )
    revenue_by_date = dict(zip(frame["report_date"], frame["revenue"], strict=True))
    profit_by_date = dict(zip(frame["report_date"], frame["parent_net_profit"], strict=True))
    equity_by_date = dict(zip(balance["report_date"], balance["parent_equity"], strict=True))

    def prior_year_same_period(report_date: date) -> date:
        return report_date.replace(year=report_date.year - 1)

    def safe_growth(current: float, previous: float | None) -> float | None:
        if previous is None or pd.isna(previous) or previous == 0 or pd.isna(current):
            return None
        return float(current / previous - 1.0)

    frame["revenue_yoy"] = [
        safe_growth(row.revenue, revenue_by_date.get(prior_year_same_period(row.report_date)))
        for row in frame.itertuples()
    ]
    frame["parent_net_profit_yoy"] = [
        safe_growth(
            row.parent_net_profit,
            profit_by_date.get(prior_year_same_period(row.report_date)),
        )
        for row in frame.itertuples()
    ]
    frame["gross_margin"] = np.where(
        frame["revenue"].notna() & (frame["revenue"] != 0) & frame["operating_cost"].notna(),
        (frame["revenue"] - frame["operating_cost"]) / frame["revenue"],
        np.nan,
    )
    frame["debt_ratio"] = np.where(
        frame["total_assets"].notna() & (frame["total_assets"] != 0),
        frame["total_liabilities"] / frame["total_assets"],
        np.nan,
    )

    def period_roe(row) -> float | None:
        current_equity = row.parent_equity
        beginning_date = date(row.report_date.year - 1, 12, 31)
        beginning_equity = equity_by_date.get(beginning_date)
        if (
            pd.isna(row.parent_net_profit)
            or pd.isna(current_equity)
            or beginning_equity is None
            or pd.isna(beginning_equity)
        ):
            return None
        average_equity = (current_equity + beginning_equity) / 2
        return float(row.parent_net_profit / average_equity) if average_equity != 0 else None

    frame["roe_period"] = [period_roe(row) for row in frame.itertuples()]
    frame["formula_version"] = FORMULA_VERSION
    frame["source"] = source
    frame["batch_id"] = batch_id
    frame["ingested_at"] = datetime.now(timezone.utc)
    columns = [
        "stock_code",
        "report_date",
        "announcement_date",
        "currency",
        "statement_scope",
        "revenue",
        "parent_net_profit",
        "operating_cash_flow",
        "revenue_yoy",
        "parent_net_profit_yoy",
        "gross_margin",
        "debt_ratio",
        "roe_period",
        "formula_version",
        "source",
        "batch_id",
        "ingested_at",
    ]
    return frame[columns].replace({np.nan: None}).sort_values("report_date").reset_index(drop=True)
