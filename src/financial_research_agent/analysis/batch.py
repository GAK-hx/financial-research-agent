from __future__ import annotations

from datetime import date, datetime, time, timezone
from uuid import uuid4

import pandas as pd
import pyarrow as pa

from financial_research_agent.analysis.engine import (
    calculate_fundamental_snapshot,
    calculate_market_factors,
)
from financial_research_agent.analysis.registry import FactorRegistry, UniverseRegistry
from financial_research_agent.analysis.repository import AnalysisRepository
from financial_research_agent.analysis.schema import (
    FACTOR_RUNS_TABLE,
    FACTOR_VALUES_TABLE,
    SECURITY_MASTER_TABLE,
    TABLE_SCHEMAS,
    UNIVERSE_MEMBERSHIP_TABLE,
)
from financial_research_agent.config import Settings
from financial_research_agent.financial.schema import METRICS_TABLE
from financial_research_agent.market.schema import KLINE_DAILY_TABLE

SECURITY_NAMES = {
    "600519": "贵州茅台", "300750": "宁德时代", "601318": "中国平安",
    "600036": "招商银行", "601166": "兴业银行", "600900": "长江电力",
    "601899": "紫金矿业", "600030": "中信证券", "601088": "中国神华",
    "600276": "恒瑞医药", "000001": "平安银行", "000333": "美的集团",
    "000651": "格力电器", "000858": "五粮液", "002594": "比亚迪",
    "002415": "海康威视", "002475": "立讯精密", "300059": "东方财富",
    "300760": "迈瑞医疗", "000725": "京东方A",
}


class SparkFactorBatch:
    """Docker batch job: Spark groups/ranks factors, PyIceberg owns durable writes."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.analysis = AnalysisRepository(settings)
        self.factor_registry = FactorRegistry.builtin()
        self.universes = UniverseRegistry.builtin()

    def run(
        self,
        *,
        universe_id: str = "demo_liquid_a_share",
        as_of_date: date | None = None,
    ) -> dict:
        try:
            from pyspark.sql import SparkSession, Window
            from pyspark.sql import functions as F
            from pyspark.sql.types import (
                DateType, DoubleType, StringType, StructField, StructType,
            )
        except ImportError as exc:
            raise RuntimeError("PYSPARK_NOT_INSTALLED_USE_ANALYSIS_PROFILE") from exc

        self.analysis.bootstrap()
        universe = self.universes.get(universe_id)
        now = datetime.now(timezone.utc)
        run_id = uuid4().hex
        market_table = self.analysis.repository.scan(KLINE_DAILY_TABLE)
        financial_table = self.analysis.repository.scan(METRICS_TABLE)
        market = market_table.to_pandas()
        financial = financial_table.to_pandas()
        observed_as_of = max(market["trade_date"]) if not market.empty else date.today()
        resolved_as_of = min(as_of_date, observed_as_of) if as_of_date else observed_as_of
        market = market[market["trade_date"] <= resolved_as_of]
        financial = financial[financial["report_date"] <= resolved_as_of]

        spark = (
            SparkSession.builder.master("local[2]")
            .appName("financial-agent-factor-batch")
            .config("spark.sql.shuffle.partitions", "4")
            .config("spark.driver.memory", "768m")
            .getOrCreate()
        )
        spark.sparkContext.setLogLevel("WARN")
        try:
            factor_schema = StructType([
                StructField("stock_code", StringType(), False),
                StructField("factor_name", StringType(), False),
                StructField("factor_value", DoubleType(), True),
                StructField("source_date", DateType(), False),
            ])

            def market_group(pdf: pd.DataFrame) -> pd.DataFrame:
                values = calculate_market_factors(pdf)
                source_date = max(pdf["trade_date"])
                return pd.DataFrame([
                    {"stock_code": str(pdf.iloc[0]["stock_code"]), "factor_name": name,
                     "factor_value": value, "source_date": source_date}
                    for name, value in values.items()
                ])

            def financial_group(pdf: pd.DataFrame) -> pd.DataFrame:
                snapshot = calculate_fundamental_snapshot(str(pdf.iloc[0]["stock_code"]), pdf)
                payload = snapshot.model_dump()
                names = (
                    "revenue_growth", "profit_growth", "roe",
                    "operating_cashflow_to_profit", "debt_to_assets",
                )
                return pd.DataFrame([
                    {"stock_code": snapshot.stock_code, "factor_name": name,
                     "factor_value": payload[name], "source_date": snapshot.report_date}
                    for name in names
                ])

            long_frames = []
            if not market.empty:
                long_frames.append(
                    spark.createDataFrame(market).groupBy("stock_code").applyInPandas(
                        market_group, schema=factor_schema
                    )
                )
            if not financial.empty:
                long_frames.append(
                    spark.createDataFrame(financial).groupBy("stock_code").applyInPandas(
                        financial_group, schema=factor_schema
                    )
                )
            if not long_frames:
                raise RuntimeError("NO_SOURCE_DATA_FOR_FACTOR_BATCH")
            values = long_frames[0]
            for item in long_frames[1:]:
                values = values.unionByName(item)

            definitions = self.factor_registry.all()
            direction_rows = [(item.name, item.direction.value) for item in definitions]
            values = values.join(
                spark.createDataFrame(direction_rows, ["factor_name", "direction"]),
                "factor_name",
            )
            ascending = Window.partitionBy("factor_name").orderBy(F.col("factor_value").asc())
            descending = Window.partitionBy("factor_name").orderBy(F.col("factor_value").desc())
            coverage = Window.partitionBy("factor_name")
            values = values.withColumn(
                "percentile_rank",
                F.when(F.col("factor_value").isNull(), F.lit(None).cast("double"))
                .when(F.col("direction") == "lower_is_better", F.percent_rank().over(descending))
                .otherwise(F.percent_rank().over(ascending)),
            ).withColumn("coverage_count", F.count("factor_value").over(coverage))

            computed = {
                (row["stock_code"], row["factor_name"]): row.asDict()
                for row in values.collect()
            }
            rows = []
            covered_stocks: set[str] = set()
            market_snapshot = self.analysis.repository.catalog.load_table(
                KLINE_DAILY_TABLE
            ).current_snapshot()
            financial_snapshot = self.analysis.repository.catalog.load_table(
                METRICS_TABLE
            ).current_snapshot()
            for stock_code in universe.members:
                for definition in definitions:
                    item = computed.get((stock_code, definition.name))
                    value = item.get("factor_value") if item else None
                    if value is not None:
                        covered_stocks.add(stock_code)
                    source_date = item.get("source_date") if item else resolved_as_of
                    available_at = datetime.combine(source_date, time.min, tzinfo=timezone.utc)
                    snapshot = (
                        market_snapshot if definition.domain.value == "market" else financial_snapshot
                    )
                    rows.append({
                        "run_id": run_id,
                        "stock_code": stock_code,
                        "as_of_date": resolved_as_of,
                        "available_at": available_at,
                        "universe_id": universe.universe_id,
                        "universe_version": universe.version,
                        "factor_name": definition.name,
                        "factor_value": value,
                        "percentile_rank": item.get("percentile_rank") if item else None,
                        "coverage_count": int(item.get("coverage_count", 0)) if item else 0,
                        "registry_version": self.factor_registry.version,
                        "formula_version": definition.formula_version,
                        "input_snapshot_id": snapshot.snapshot_id if snapshot else None,
                        "status": "valid" if value is not None else "missing",
                        "missing_reason": None if value is not None else "NO_SOURCE_DATA_OR_INSUFFICIENT_WINDOW",
                        "point_in_time_eligible": definition.point_in_time_eligible,
                        "computed_at": now,
                    })
            self._seed_metadata(universe, now)
            factor_arrow = pa.Table.from_pylist(rows, schema=TABLE_SCHEMAS[FACTOR_VALUES_TABLE].as_arrow())
            self.analysis.append(FACTOR_VALUES_TABLE, factor_arrow)
            finished = datetime.now(timezone.utc)
            run_row = {
                "run_id": run_id,
                "universe_id": universe.universe_id,
                "universe_version": universe.version,
                "as_of_date": resolved_as_of,
                "registry_version": self.factor_registry.version,
                "market_snapshot_id": market_snapshot.snapshot_id if market_snapshot else None,
                "financial_snapshot_id": financial_snapshot.snapshot_id if financial_snapshot else None,
                "universe_size": len(universe.members),
                "covered_stocks": len(covered_stocks),
                "factor_rows": len(rows),
                "engine": f"pyspark-{spark.version}+pyiceberg",
                "status": "SUCCESS",
                "started_at": now,
                "finished_at": finished,
            }
            self.analysis.append(
                FACTOR_RUNS_TABLE,
                pa.Table.from_pylist([run_row], schema=TABLE_SCHEMAS[FACTOR_RUNS_TABLE].as_arrow()),
            )
            return run_row
        finally:
            spark.stop()

    def _seed_metadata(self, universe, now: datetime) -> None:
        security_table = self.analysis.repository.catalog.load_table(SECURITY_MASTER_TABLE)
        if security_table.scan().to_arrow().num_rows == 0:
            rows = [{
                "stock_code": code,
                "display_name": SECURITY_NAMES.get(code, code),
                "exchange": "SSE" if code.startswith("6") else "SZSE",
                "asset_type": "A_SHARE",
                "effective_date": universe.effective_date,
                "version": universe.version,
                "loaded_at": now,
            } for code in universe.members]
            self.analysis.append(
                SECURITY_MASTER_TABLE,
                pa.Table.from_pylist(rows, schema=TABLE_SCHEMAS[SECURITY_MASTER_TABLE].as_arrow()),
            )
        membership = self.analysis.repository.catalog.load_table(UNIVERSE_MEMBERSHIP_TABLE)
        if membership.scan().to_arrow().num_rows == 0:
            rows = [{
                "universe_id": universe.universe_id,
                "universe_version": universe.version,
                "effective_date": universe.effective_date,
                "stock_code": code,
                "selection_policy": universe.selection_policy,
                "loaded_at": now,
            } for code in universe.members]
            self.analysis.append(
                UNIVERSE_MEMBERSHIP_TABLE,
                pa.Table.from_pylist(rows, schema=TABLE_SCHEMAS[UNIVERSE_MEMBERSHIP_TABLE].as_arrow()),
            )
