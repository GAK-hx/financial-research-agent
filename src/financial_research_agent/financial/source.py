from __future__ import annotations

from typing import Protocol

import pandas as pd

STATEMENT_SOURCE_NAMES = {
    "income": "利润表",
    "balance": "资产负债表",
    "cash_flow": "现金流量表",
}


class FinancialStatementSource(Protocol):
    name: str
    endpoint: str
    mapping_version: str

    def fetch(self, stock_code: str, statement: str) -> pd.DataFrame: ...


class AkShareFinancialStatementSource:
    name = "akshare"
    endpoint = "stock_financial_report_sina"
    mapping_version = "sina_financial_statements_v1"

    def fetch(self, stock_code: str, statement: str) -> pd.DataFrame:
        import akshare as ak

        prefix = "sh" if stock_code.startswith("6") else "sz"
        return ak.stock_financial_report_sina(
            stock=f"{prefix}{stock_code}",
            symbol=STATEMENT_SOURCE_NAMES[statement],
        )
