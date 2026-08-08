from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Protocol

import pandas as pd


class DailyMarketSource(Protocol):
    name: str
    endpoint: str
    mapping_version: str

    def fetch(self, symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame: ...


class AkShareDailyMarketSource:
    name = "akshare"
    endpoint = "stock_zh_a_hist|stock_zh_a_hist_tx"
    mapping_version = "akshare_daily_fallback_v2"

    def __init__(
        self,
        *,
        max_retries: int = 5,
        retry_backoff_seconds: float = 3.0,
        retry_max_backoff_seconds: float = 20.0,
    ) -> None:
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.retry_max_backoff_seconds = retry_max_backoff_seconds

    def fetch(self, symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
        import akshare as ak

        for attempt in range(self.max_retries + 1):
            try:
                frame = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust,
                )
                frame.attrs["source_endpoint"] = "stock_zh_a_hist"
                return frame
            except Exception as primary_error:
                try:
                    return self._fetch_tencent(
                        ak,
                        symbol=symbol,
                        start_date=start_date,
                        end_date=end_date,
                        adjust=adjust,
                    )
                except Exception as fallback_error:
                    if attempt >= self.max_retries:
                        raise RuntimeError(
                            "both AkShare daily market endpoints failed; "
                            f"primary={type(primary_error).__name__}; "
                            f"fallback={type(fallback_error).__name__}"
                        ) from fallback_error
                if attempt >= self.max_retries:
                    raise
                delay = min(
                    self.retry_backoff_seconds * (2**attempt),
                    self.retry_max_backoff_seconds,
                )
                time.sleep(delay)
        raise RuntimeError("market source retry loop exited unexpectedly")

    @staticmethod
    def _fetch_tencent(
        ak,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
        adjust: str,
    ) -> pd.DataFrame:
        market_symbol = f"sh{symbol}" if symbol.startswith("6") else f"sz{symbol}"
        requested_start = datetime.strptime(start_date, "%Y%m%d")
        lookback_start = (requested_start - timedelta(days=10)).strftime("%Y%m%d")
        frame = ak.stock_zh_a_hist_tx(
            symbol=market_symbol,
            start_date=lookback_start,
            end_date=end_date,
            adjust=adjust,
        ).copy()
        required = {
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "turnover",
        }
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"Tencent source fields missing: {', '.join(sorted(missing))}")
        frame["date"] = pd.to_datetime(frame["date"], errors="raise")
        frame = frame.sort_values("date").reset_index(drop=True)
        previous_close = frame["close"].shift(1)
        adapted = pd.DataFrame(
            {
                "日期": frame["date"],
                "开盘": frame["open"],
                "收盘": frame["close"],
                "最高": frame["high"],
                "最低": frame["low"],
                # Eastmoney uses lots while Tencent documents shares.
                "成交量": (frame["volume"] / 100).round(),
                "成交额": frame["amount"],
                "振幅": (frame["high"] - frame["low"]) / previous_close * 100,
                "涨跌幅": (frame["close"] / previous_close - 1) * 100,
                "涨跌额": frame["close"] - previous_close,
                # Eastmoney reports percent while Tencent reports a fraction.
                "换手率": frame["turnover"] * 100,
            }
        )
        requested_end = datetime.strptime(end_date, "%Y%m%d")
        adapted = adapted.loc[
            (adapted["日期"] >= requested_start)
            & (adapted["日期"] <= requested_end)
        ].reset_index(drop=True)
        adapted.attrs["source_endpoint"] = "stock_zh_a_hist_tx"
        return adapted
