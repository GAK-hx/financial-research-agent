import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from financial_research_agent.config import get_settings
from financial_research_agent.financial.normalize import calculate_metrics, normalize_statement
from financial_research_agent.financial.schema import (
    BALANCE_TABLE,
    CASH_FLOW_TABLE,
    INCOME_TABLE,
    METRICS_TABLE,
)
from financial_research_agent.repositories.iceberg import IcebergRepository

COMPARE_FIELDS = [
    "revenue",
    "parent_net_profit",
    "operating_cash_flow",
    "revenue_yoy",
    "parent_net_profit_yoy",
    "gross_margin",
    "debt_ratio",
    "roe_period",
]


def _latest_raw(root: Path, dataset: str) -> pd.DataFrame:
    path = sorted((root / "raw" / dataset).glob("batch_id=*/part-00000.parquet"))[-1]
    return pq.ParquetFile(path).read().to_pandas()


def _equal(left, right) -> bool:
    if pd.isna(left) and pd.isna(right):
        return True
    return abs(float(left) - float(right)) < 1e-10


def main() -> None:
    settings = get_settings()
    repository = IcebergRepository(settings)
    tables = {}
    for identifier in [INCOME_TABLE, BALANCE_TABLE, CASH_FLOW_TABLE, METRICS_TABLE]:
        frame = repository.scan(identifier).to_pandas()
        tables[identifier] = {
            "rows": len(frame),
            "duplicate_keys": int(frame.duplicated(["stock_code", "report_date"]).sum()),
        }
    curated = repository.scan(METRICS_TABLE).to_pandas()
    sample_matches = 0
    sample_total = 0
    stock_ranges = []
    root = Path(settings.lake_root)
    for stock_code in settings.stock_codes:
        normalized = {}
        for statement in ["income", "balance", "cash_flow"]:
            raw = _latest_raw(root, f"financial_{statement}_{stock_code}")
            normalized[statement], _ = normalize_statement(
                raw, statement, stock_code, "akshare", "audit"
            )
        expected = calculate_metrics(
            normalized["income"], normalized["balance"], normalized["cash_flow"], "audit", "akshare"
        ).tail(5)
        actual = curated.loc[curated["stock_code"] == stock_code]
        joined = expected.merge(actual, on=["stock_code", "report_date"], suffixes=("_expected", "_actual"))
        for row in joined.itertuples():
            sample_total += 1
            if all(
                _equal(getattr(row, f"{field}_expected"), getattr(row, f"{field}_actual"))
                for field in COMPARE_FIELDS
            ):
                sample_matches += 1
        stock_ranges.append(
            {
                "stock_code": stock_code,
                "periods": len(actual),
                "min_report_date": str(actual["report_date"].min()),
                "max_report_date": str(actual["report_date"].max()),
            }
        )
    result = {
        "tables": tables,
        "stocks": stock_ranges,
        "sample_matches": sample_matches,
        "sample_total": sample_total,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if any(item["duplicate_keys"] for item in tables.values()) or sample_matches != sample_total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
