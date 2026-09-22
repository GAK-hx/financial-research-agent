from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import pyarrow as pa
from pyiceberg.catalog import load_catalog
from pyiceberg.expressions import EqualTo
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.transforms import IdentityTransform
from pyiceberg.types import (
    DoubleType,
    IntegerType,
    LongType,
    NestedField,
    StringType,
)


AGGREGATE_SCHEMA = Schema(
    NestedField(1, "issuer_id", StringType(), required=True),
    NestedField(2, "issuer_group", IntegerType(), required=True),
    NestedField(3, "report_year", IntegerType(), required=True),
    NestedField(4, "metric_code", StringType(), required=True),
    NestedField(5, "avg_value", DoubleType(), required=True),
    NestedField(6, "observation_count", LongType(), required=True),
    NestedField(7, "batch_id", StringType(), required=True),
)


def _directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _spark(output_root: Path, cpu_count: int):
    try:
        from pyspark.sql import SparkSession
    except ImportError as exc:
        raise RuntimeError("PYSPARK_NOT_INSTALLED_USE_ANALYSIS_PROFILE") from exc
    return (
        SparkSession.builder.master(f"local[{cpu_count}]")
        .appName("financial-agent-spark-iceberg-validation")
        .config("spark.sql.shuffle.partitions", "32")
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.sql.execution.arrow.pyspark.enabled", "true")
        .config("spark.driver.memory", "3g")
        .config("spark.local.dir", str(output_root / "spark-local"))
        .getOrCreate()
    )


def _generate_source(spark: Any, path: Path, row_count: int) -> float:
    from pyspark.sql import functions as F

    started = time.perf_counter()
    issuer_index = F.pmod(F.col("id"), F.lit(1000)).cast("int")
    source = (
        spark.range(0, row_count, 1, numPartitions=32)
        .withColumn("issuer_index", issuer_index)
        .withColumn("issuer_id", F.format_string("%06d", F.col("issuer_index")))
        .withColumn("issuer_group", F.pmod(F.col("issuer_index"), F.lit(20)))
        .withColumn(
            "report_year",
            (
                F.lit(2015)
                + F.pmod((F.col("id") / F.lit(1000)).cast("long"), F.lit(10))
            ).cast("int"),
        )
        .withColumn(
            "metric_code",
            F.concat(
                F.lit("metric_"),
                F.lpad(
                    F.pmod(
                        (F.col("id") / F.lit(10_000)).cast("long"), F.lit(12)
                    ).cast("string"),
                    2,
                    "0",
                ),
            ),
        )
        .withColumn(
            "value",
            (F.pmod(F.col("id") * F.lit(13), F.lit(100_000)) / F.lit(100.0)).cast(
                "double"
            ),
        )
        .select(
            "id",
            "issuer_id",
            "issuer_group",
            "report_year",
            "metric_code",
            "value",
        )
        .repartition(20, "issuer_group")
    )
    (
        source.write.mode("overwrite")
        # The hardened container keeps /tmp non-executable. Gzip avoids Spark's
        # zstd-jni extraction while preserving compressed, portable Parquet.
        .option("compression", "gzip")
        .option("maxRecordsPerFile", 500_000)
        .partitionBy("issuer_group", "report_year")
        .parquet(str(path))
    )
    return time.perf_counter() - started


def _aggregate(frame: Any, batch_id: str) -> Any:
    from pyspark.sql import functions as F

    return (
        frame.groupBy("issuer_id", "issuer_group", "report_year", "metric_code")
        .agg(
            F.avg("value").alias("avg_value"),
            F.count(F.lit(1)).cast("long").alias("observation_count"),
        )
        .withColumn("batch_id", F.lit(batch_id))
        .select(*[field.name for field in AGGREGATE_SCHEMA.fields])
    )


def _to_arrow(frame: Any) -> pa.Table:
    pandas_frame = frame.orderBy(
        "issuer_group", "issuer_id", "report_year", "metric_code"
    ).toPandas()
    return pa.Table.from_pandas(
        pandas_frame, schema=AGGREGATE_SCHEMA.as_arrow(), preserve_index=False
    )


def _data_file_stats(table: Any) -> dict[str, Any]:
    rows = table.inspect.data_files().to_pylist()
    sizes = [int(row["file_size_in_bytes"]) for row in rows]
    return {
        "file_count": len(rows),
        "total_bytes": sum(sizes),
        "min_bytes": min(sizes) if sizes else 0,
        "max_bytes": max(sizes) if sizes else 0,
        "average_bytes": round(sum(sizes) / len(sizes), 2) if sizes else 0,
        "files_under_64k": sum(size < 65_536 for size in sizes),
    }


def _snapshot_id(table: Any) -> int | None:
    snapshot = table.current_snapshot()
    return snapshot.snapshot_id if snapshot else None


def _markdown(report: dict[str, Any]) -> str:
    full = report["spark"]["full"]
    incremental = report["spark"]["incremental"]
    pruning = report["iceberg"]["partition_pruning"]
    recovery = report["iceberg"]["failure_recovery"]
    return "\n".join(
        [
            "# Spark / Iceberg 增量与恢复验证",
            "",
            f"- 状态：`{report['status']}`；",
            f"- 合成输入：{report['source']['rows']:,} 行，只用于性能与恢复测试；",
            f"- Spark：`{report['spark']['version']}`，{report['resources']['cpu']} CPU；",
            f"- 源数据存储：{report['source']['storage_bytes'] / 1024 / 1024:.1f} MiB；",
            "",
            "## 全量与增量",
            "",
            f"- 全量扫描/聚合：{full['input_rows']:,} / {full['output_rows']:,} 行，"
            f"{full['seconds']:.3f} 秒；",
            f"- 增量扫描/聚合：{incremental['input_rows']:,} / "
            f"{incremental['output_rows']:,} 行，{incremental['seconds']:.3f} 秒；",
            f"- 增量扫描行减少：{incremental['row_scan_reduction']:.1%}；",
            "- 增量边界：`issuer_group=0`，即50/1000家公司。",
            "",
            "## Iceberg分区与快照",
            "",
            f"- 全表计划文件：{pruning['full_files']}；",
            f"- 单公司组计划文件：{pruning['filtered_files']}；",
            f"- 文件裁剪：{pruning['file_reduction']:.1%}；",
            f"- 当前数据文件：{report['iceberg']['data_files']['file_count']}，"
            f"其中小于64 KiB为{report['iceberg']['data_files']['files_under_64k']}；",
            "",
            "## 失败恢复与幂等",
            "",
            f"- 注入失败：`{recovery['failure_type']}`；",
            f"- 失败前后 Snapshot 未变化：{str(recovery['snapshot_unchanged_after_failure']).lower()}；",
            f"- 恢复提交后 Snapshot 前进：{str(recovery['snapshot_advanced_after_recovery']).lower()}；",
            f"- 相同增量批次重跑后业务主键重复：{recovery['duplicate_primary_keys_after_rerun']}；",
            f"- 未受影响分区值变化：{recovery['unaffected_value_changes']}；",
            "",
            "## 验收",
            "",
            *[
                f"- [{'x' if passed else ' '}] `{name}`"
                for name, passed in report["checks"].items()
            ],
            "",
            "本报告的行数和文件裁剪是可复核结果；耗时仅作当前Docker环境诊断，不作为生产SLA或简历数字。",
            "",
        ]
    )


def run_validation(
    output_root: Path,
    *,
    row_count: int = 5_000_000,
    cpu_count: int = 4,
) -> dict[str, Any]:
    if row_count < 100_000:
        raise ValueError("row_count must be at least 100,000 for this performance validation")
    output_root.mkdir(parents=True, exist_ok=True)
    source_root = output_root / "synthetic_source"
    spark = _spark(output_root, cpu_count)
    spark.sparkContext.setLogLevel("WARN")
    try:
        source_generation_seconds = _generate_source(spark, source_root, row_count)
        source = spark.read.parquet(str(source_root))

        full_started = time.perf_counter()
        full_input_rows = source.count()
        full_arrow = _to_arrow(_aggregate(source, "full-v1"))
        full_seconds = time.perf_counter() - full_started

        incremental_source = source.where("issuer_group = 0").withColumn(
            "value", source["value"] + 7.0
        )
        incremental_started = time.perf_counter()
        incremental_input_rows = incremental_source.count()
        incremental_arrow = _to_arrow(
            _aggregate(incremental_source, "incremental-v2")
        )
        incremental_seconds = time.perf_counter() - incremental_started
        executed_plan = incremental_source._jdf.queryExecution().executedPlan().toString()

        iceberg_root = output_root / "iceberg"
        warehouse = iceberg_root / "warehouse"
        warehouse.mkdir(parents=True, exist_ok=True)
        catalog = load_catalog(
            "risk_validation",
            type="sql",
            uri=f"sqlite:///{iceberg_root / 'catalog.db'}",
            warehouse=f"file://{warehouse}",
        )
        if ("simulation",) not in catalog.list_namespaces():
            catalog.create_namespace("simulation")
        identifier = "simulation.risk_metric_aggregate_perf"
        if catalog.table_exists(identifier):
            catalog.drop_table(identifier)
        table = catalog.create_table(
            identifier,
            schema=AGGREGATE_SCHEMA,
            partition_spec=PartitionSpec(
                PartitionField(
                    source_id=2,
                    field_id=1001,
                    transform=IdentityTransform(),
                    name="issuer_group",
                )
            ),
            properties={"write.target-file-size-bytes": str(64 * 1024 * 1024)},
        )
        table.append(full_arrow, snapshot_properties={"batch_id": "full-v1"})
        initial_snapshot = _snapshot_id(table)
        initial_rows = table.scan().to_arrow().num_rows

        malformed = incremental_arrow.drop(["batch_id"])
        failure_type = ""
        try:
            table.dynamic_partition_overwrite(malformed)
        except Exception as exc:
            failure_type = type(exc).__name__
        table.refresh()
        snapshot_after_failure = _snapshot_id(table)

        table.dynamic_partition_overwrite(
            incremental_arrow, snapshot_properties={"batch_id": "incremental-v2"}
        )
        table.refresh()
        recovery_snapshot = _snapshot_id(table)
        table.dynamic_partition_overwrite(
            incremental_arrow,
            snapshot_properties={"batch_id": "incremental-v2-rerun"},
        )
        table.refresh()
        rerun_snapshot = _snapshot_id(table)
        final_arrow = table.scan().to_arrow()
        final_frame = final_arrow.to_pandas()
        primary_key = ["issuer_id", "issuer_group", "report_year", "metric_code"]
        duplicate_primary_keys = int(final_frame.duplicated(primary_key).sum())

        full_frame = full_arrow.to_pandas()
        unaffected_before = full_frame[full_frame["issuer_group"] != 0].sort_values(
            primary_key
        )
        unaffected_after = final_frame[final_frame["issuer_group"] != 0].sort_values(
            primary_key
        )
        unaffected_value_changes = int(
            (unaffected_before["avg_value"].to_numpy() != unaffected_after["avg_value"].to_numpy()).sum()
        )
        full_files = len(list(table.scan().plan_files()))
        filtered_files = len(
            list(table.scan(row_filter=EqualTo("issuer_group", 0)).plan_files())
        )
        file_reduction = 1 - filtered_files / full_files if full_files else 0.0
        row_reduction = 1 - incremental_input_rows / full_input_rows
        file_stats = _data_file_stats(table)

        checks = {
            "requested_source_rows_materialized": full_input_rows == row_count,
            "incremental_row_scan_reduction_significant": row_reduction >= 0.80,
            "spark_partition_filter_present": "PartitionFilters" in executed_plan
            and "issuer_group" in executed_plan,
            "iceberg_file_pruning_significant": file_reduction >= 0.80,
            "failure_did_not_commit_snapshot": bool(failure_type)
            and initial_snapshot == snapshot_after_failure,
            "recovery_committed_new_snapshot": recovery_snapshot not in {
                None,
                initial_snapshot,
            },
            "rerun_preserved_business_keys": final_arrow.num_rows == initial_rows
            and duplicate_primary_keys == 0,
            "unaffected_partitions_unchanged": unaffected_value_changes == 0,
        }
        report = {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "validation": "spark_iceberg_incremental",
            "synthetic_data_only": True,
            "accuracy_claimed": False,
            "resources": {"cpu": cpu_count, "container_memory_gib": 6},
            "source": {
                "rows": full_input_rows,
                "issuer_count": 1000,
                "issuer_groups": 20,
                "years": 10,
                "metric_codes": 12,
                "generation_seconds": round(source_generation_seconds, 3),
                "storage_bytes": _directory_bytes(source_root),
            },
            "spark": {
                "version": spark.version,
                "full": {
                    "input_rows": full_input_rows,
                    "output_rows": full_arrow.num_rows,
                    "seconds": round(full_seconds, 3),
                },
                "incremental": {
                    "input_rows": incremental_input_rows,
                    "output_rows": incremental_arrow.num_rows,
                    "affected_issuer_group": 0,
                    "affected_issuer_count": 50,
                    "row_scan_reduction": round(row_reduction, 4),
                    "seconds": round(incremental_seconds, 3),
                    "partition_filter_visible_in_plan": "PartitionFilters" in executed_plan,
                },
            },
            "iceberg": {
                "table": identifier,
                "partition_spec": "identity(issuer_group)",
                "initial_snapshot_id": initial_snapshot,
                "recovery_snapshot_id": recovery_snapshot,
                "rerun_snapshot_id": rerun_snapshot,
                "final_rows": final_arrow.num_rows,
                "data_files": file_stats,
                "partition_pruning": {
                    "full_files": full_files,
                    "filtered_files": filtered_files,
                    "file_reduction": round(file_reduction, 4),
                },
                "failure_recovery": {
                    "failure_type": failure_type,
                    "snapshot_unchanged_after_failure": initial_snapshot
                    == snapshot_after_failure,
                    "snapshot_advanced_after_recovery": recovery_snapshot
                    not in {None, initial_snapshot},
                    "duplicate_primary_keys_after_rerun": duplicate_primary_keys,
                    "unaffected_value_changes": unaffected_value_changes,
                },
            },
            "checks": checks,
            "notes": [
                "Synthetic rows validate data-engineering behavior only.",
                "PySpark performs generation and aggregation; PyIceberg owns atomic table commits.",
                "Timing is local Docker diagnostic data, not a production SLA or resume metric.",
            ],
        }
        (output_root / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (output_root / "report.md").write_text(_markdown(report), encoding="utf-8")
        return report
    finally:
        spark.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Spark and Iceberg incremental processing")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=5_000_000)
    parser.add_argument("--cpus", type=int, default=4)
    args = parser.parse_args()
    report = run_validation(args.output_root, row_count=args.rows, cpu_count=args.cpus)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
