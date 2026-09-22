from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


N_SPLITS = 5
RANDOM_STATE = 42


def build_fold_assignments(frame: pd.DataFrame) -> np.ndarray:
    missing = {"country", "company"} - set(frame.columns)
    if missing:
        raise ValueError(f"missing official fold columns: {sorted(missing)}")
    rng = np.random.RandomState(RANDOM_STATE)
    group_to_fold: dict[tuple[object, object], int] = {}
    for country, country_frame in frame.groupby("country"):
        companies = country_frame["company"].dropna().unique().copy()
        rng.shuffle(companies)
        for index, company in enumerate(companies):
            group_to_fold[(country, company)] = index % N_SPLITS
    assignments = np.empty(len(frame), dtype=np.int8)
    for position, row in enumerate(frame[["country", "company"]].itertuples(index=False)):
        try:
            assignments[position] = group_to_fold[(row[0], row[1])]
        except KeyError as exc:
            raise ValueError(f"cannot assign row {position}: {(row[0], row[1])}") from exc
    return assignments


def _split_summary(frame: pd.DataFrame, assignments: np.ndarray) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for fold in range(N_SPLITS):
        selected = assignments == fold
        labels = frame.loc[selected, "main_label"]
        countries = frame.loc[selected, "country"].value_counts().sort_index()
        summary[str(fold)] = {
            "rows": int(selected.sum()),
            "positives": int(labels.sum()),
            "prevalence": float(labels.mean()),
            "country_rows": {str(int(k)): int(v) for k, v in countries.items()},
        }
    return summary


def prepare_folds(*, data_path: Path, output_root: Path) -> dict[str, Any]:
    table = pq.read_table(
        data_path,
        columns=["country", "company", "main_label"],
    )
    frame = table.to_pandas()
    if frame[["country", "company", "main_label"]].isna().any().any():
        raise ValueError("official fold or target columns contain null values")
    assignments = build_fold_assignments(frame)
    grouped = pd.DataFrame(
        {
            "country": frame["country"],
            "company": frame["company"],
            "fold": assignments,
        }
    ).groupby(["country", "company"])["fold"].nunique()
    leaking_groups = int((grouped > 1).sum())
    if leaking_groups:
        raise ValueError(f"company-group leakage detected for {leaking_groups} groups")

    output_root.mkdir(parents=True, exist_ok=True)
    assignment_path = output_root / "fold_assignments.parquet"
    pq.write_table(
        pa.table(
            {
                "row_index": np.arange(len(frame), dtype=np.int64),
                "fold": assignments,
            }
        ),
        assignment_path,
        compression="zstd",
    )
    report = {
        "status": "READY",
        "source_protocol": "genwro-ai/V4FinBench official grouped folds",
        "rows": len(frame),
        "n_splits": N_SPLITS,
        "random_state": RANDOM_STATE,
        "country_col": "country",
        "group_col": "company",
        "target_col": "main_label",
        "company_group_leaks": leaking_groups,
        "assignment_path": str(assignment_path),
        "folds": _split_summary(frame, assignments),
        "rotation": {
            str(fold): {
                "validation_fold": fold,
                "test_fold": (fold + 1) % N_SPLITS,
                "training_folds": [
                    item
                    for item in range(N_SPLITS)
                    if item not in {fold, (fold + 1) % N_SPLITS}
                ],
            }
            for fold in range(N_SPLITS)
        },
    }
    (output_root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    rows = [
        "# V4FinBench 官方分组折",
        "",
        f"- 行数：{len(frame):,}；",
        f"- 折数：{N_SPLITS}；",
        f"- 随机种子：{RANDOM_STATE}；",
        "- 分组键：`country + company`；",
        f"- 跨折公司组：{leaking_groups}；",
        "",
        "| Fold | 行数 | 正类 | 正类率 |",
        "|---:|---:|---:|---:|",
    ]
    for fold, item in report["folds"].items():
        rows.append(
            f"| {fold} | {item['rows']:,} | {item['positives']:,} | "
            f"{item['prevalence']:.4%} |"
        )
    (output_root / "report.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build official V4FinBench grouped folds")
    parser.add_argument(
        "--data",
        default="/artifacts/phase5_step02/v4finbench_h1_v1/company_years_h2.parquet",
    )
    parser.add_argument(
        "--output-root", default="/artifacts/phase5_step02/v4finbench_h1_v1/folds"
    )
    args = parser.parse_args()
    report = prepare_folds(data_path=Path(args.data), output_root=Path(args.output_root))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
