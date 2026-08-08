from __future__ import annotations

import math

import pandas as pd

from financial_research_agent.analysis.models import (
    FundamentalSnapshot,
    TechnicalSnapshot,
)

FACTOR_REGISTRY_VERSION = "factor_registry_v1"
TECHNICAL_FORMULA_VERSION = "technical_analysis_v1"
FUNDAMENTAL_FORMULA_VERSION = "fundamental_analysis_v1"


def _return(close: pd.Series, periods: int) -> float | None:
    if len(close) <= periods or close.iloc[-periods - 1] == 0:
        return None
    return float(close.iloc[-1] / close.iloc[-periods - 1] - 1.0)


def calculate_market_factors(frame: pd.DataFrame) -> dict[str, float | None]:
    """Calculate the market-domain registry factors from sorted qfq daily bars."""
    if frame.empty:
        return {
            name: None
            for name in (
                "momentum_20d",
                "momentum_60d",
                "reversal_5d",
                "volatility_20d",
                "max_drawdown_60d",
                "relative_volume_20d",
                "amihud_liquidity_20d",
            )
        }
    ordered = frame.sort_values("trade_date").reset_index(drop=True)
    close = ordered["close"].astype(float)
    volume = ordered["volume"].astype(float)
    amount = ordered["amount"].astype(float)
    daily_return = close.pct_change()
    volatility = None
    if len(close) >= 21:
        window_returns = daily_return.tail(20).dropna()
        if len(window_returns) == 20:
            volatility = float(window_returns.std(ddof=1) * math.sqrt(252))
    drawdown = None
    if len(close) >= 2:
        drawdown_window = close.tail(60)
        drawdown = float(abs((drawdown_window / drawdown_window.cummax() - 1.0).min()))
    relative_volume = None
    if len(volume) >= 20 and volume.tail(20).mean() > 0:
        relative_volume = float(volume.iloc[-1] / volume.tail(20).mean())
    amihud = None
    if len(close) >= 21:
        paired = pd.DataFrame(
            {"return": daily_return.tail(20), "amount": amount.tail(20)}
        ).dropna()
        paired = paired[paired["amount"] > 0]
        if len(paired) == 20:
            amihud = float((paired["return"].abs() / paired["amount"]).mean() * 1e8)
    reversal = _return(close, 5)
    return {
        "momentum_20d": _return(close, 20),
        "momentum_60d": _return(close, 60),
        "reversal_5d": -reversal if reversal is not None else None,
        "volatility_20d": volatility,
        "max_drawdown_60d": drawdown,
        "relative_volume_20d": relative_volume,
        "amihud_liquidity_20d": amihud,
    }


def calculate_technical_snapshot(stock_code: str, frame: pd.DataFrame) -> TechnicalSnapshot:
    if frame.empty:
        raise ValueError("technical analysis requires at least one daily bar")
    ordered = frame.sort_values("trade_date").reset_index(drop=True)
    close = ordered["close"].astype(float)
    values = calculate_market_factors(ordered)
    ma5 = float(close.tail(5).mean()) if len(close) >= 5 else None
    ma20 = float(close.tail(20).mean()) if len(close) >= 20 else None
    if ma5 is None or ma20 is None:
        trend = "insufficient"
    elif close.iloc[-1] > ma5 > ma20:
        trend = "bullish"
    elif close.iloc[-1] < ma5 < ma20:
        trend = "bearish"
    else:
        trend = "mixed"
    return TechnicalSnapshot(
        stock_code=stock_code,
        as_of_date=ordered.iloc[-1]["trade_date"],
        observations=len(ordered),
        close=float(close.iloc[-1]),
        ma5=ma5,
        ma20=ma20,
        trend_state=trend,
        formula_version=TECHNICAL_FORMULA_VERSION,
        **values,
    )


def calculate_fundamental_snapshot(
    stock_code: str, frame: pd.DataFrame
) -> FundamentalSnapshot:
    if frame.empty:
        raise ValueError("fundamental analysis requires at least one financial period")
    latest = frame.sort_values("report_date").iloc[-1]

    def value(name: str) -> float | None:
        raw = latest.get(name)
        return None if raw is None or pd.isna(raw) else float(raw)

    profit = value("parent_net_profit")
    cashflow = value("operating_cash_flow")
    ratio = None if profit in {None, 0.0} or cashflow is None else cashflow / profit
    announcement = latest.get("announcement_date")
    if announcement is not None and pd.isna(announcement):
        announcement = None
    return FundamentalSnapshot(
        stock_code=stock_code,
        report_date=latest["report_date"],
        available_at=announcement,
        revenue_growth=value("revenue_yoy"),
        profit_growth=value("parent_net_profit_yoy"),
        roe=value("roe_period"),
        operating_cashflow_to_profit=ratio,
        debt_to_assets=value("debt_ratio"),
        point_in_time_eligible=False,
        data_limitations=[
            "公告日期可能来自后续更新，当前结果仅用于最新快照分析，不用于历史时点回测。"
        ],
        formula_version=FUNDAMENTAL_FORMULA_VERSION,
    )
