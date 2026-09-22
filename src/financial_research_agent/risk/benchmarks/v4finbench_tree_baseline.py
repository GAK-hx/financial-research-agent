from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from financial_research_agent.risk.benchmarks.v4finbench_baseline import (
    N_SPLITS,
    _best_f1_threshold,
    _calibrate,
    _fit_platt_calibrator,
    _metrics,
    _numeric_features,
    _replace_nonfinite_and_impute,
    _summary,
)


def run_lightgbm_baseline(
    *,
    data_path: Path,
    folds_path: Path,
    output_root: Path,
    selected_folds: list[int],
    resume: bool,
) -> dict[str, Any]:
    try:
        from lightgbm import LGBMClassifier
    except ImportError as exc:
        raise RuntimeError("LightGBM is required in the ingestion image") from exc

    output_root.mkdir(parents=True, exist_ok=True)
    results_path = output_root / "fold_results.json"
    results: list[dict[str, Any]] = (
        json.loads(results_path.read_text(encoding="utf-8"))
        if resume and results_path.exists()
        else []
    )
    completed = {int(row["rotation_fold"]) for row in results}
    feature_names = _numeric_features(pq.read_schema(data_path))
    table = pq.read_table(data_path, columns=[*feature_names, "main_label"])
    frame = table.to_pandas()
    raw_countries = frame["country"].to_numpy(dtype=np.int16, copy=True)
    labels = frame["main_label"].to_numpy(dtype=np.int8, copy=True)
    features = frame[feature_names].to_numpy(dtype=np.float32, copy=True)
    del frame, table
    assignments = (
        pq.read_table(folds_path, columns=["fold"])["fold"]
        .to_numpy()
        .astype(np.int8, copy=False)
    )
    if len(features) != len(assignments):
        raise ValueError("fold assignments do not match V4FinBench rows")

    for rotation_fold in selected_folds:
        prediction_path = output_root / f"fold_{rotation_fold}_predictions.parquet"
        if rotation_fold in completed and prediction_path.exists():
            continue
        validation_fold = rotation_fold
        test_fold = (rotation_fold + 1) % N_SPLITS
        train_mask = (assignments != validation_fold) & (assignments != test_fold)
        validation_mask = assignments == validation_fold
        test_mask = assignments == test_fold
        train_x = features[train_mask].copy()
        validation_x = features[validation_mask].copy()
        test_x = features[test_mask].copy()
        train_x, validation_x, test_x, all_nan_training_features = (
            _replace_nonfinite_and_impute(train_x, validation_x, test_x)
        )
        train_y = labels[train_mask]
        positive = int((train_y == 1).sum())
        model = LGBMClassifier(
            # A single fixed configuration from the public benchmark's
            # LightGBM search space.  This is intentionally not tuned per fold.
            n_estimators=200,
            learning_rate=0.05,
            max_depth=-1,
            importance_type="gain",
            random_state=42,
            n_jobs=4,
            verbosity=-1,
        )
        model.fit(train_x, train_y)
        validation_raw_scores = model.predict_proba(validation_x)[:, 1]
        calibrator = _fit_platt_calibrator(
            labels[validation_mask], validation_raw_scores
        )
        validation_scores = _calibrate(calibrator, validation_raw_scores)
        threshold = _best_f1_threshold(labels[validation_mask], validation_scores)
        test_raw_scores = model.predict_proba(test_x)[:, 1]
        test_scores = _calibrate(calibrator, test_raw_scores)
        ranked_features = sorted(
            zip(feature_names, model.feature_importances_, strict=True),
            key=lambda item: float(item[1]),
            reverse=True,
        )
        result = {
            "model": "lightgbm_fixed",
            "paper_horizon": 1,
            "rotation_fold": rotation_fold,
            "validation_fold": validation_fold,
            "test_fold": test_fold,
            "training_folds": [
                fold
                for fold in range(N_SPLITS)
                if fold not in {validation_fold, test_fold}
            ],
            "train_rows": int(train_mask.sum()),
            "validation_rows": int(validation_mask.sum()),
            "test_rows": int(test_mask.sum()),
            "train_positives": positive,
            "validation_positives": int(labels[validation_mask].sum()),
            "test_positives": int(labels[test_mask].sum()),
            "feature_count": len(feature_names),
            "all_nan_training_features": all_nan_training_features,
            "fixed_parameters": {
                "n_estimators": 200,
                "learning_rate": 0.05,
                "max_depth": -1,
            },
            "probability_calibration": "Platt scaling fitted on validation fold",
            "calibration_coefficient": float(calibrator.coef_[0, 0]),
            "calibration_intercept": float(calibrator.intercept_[0]),
            "threshold_selected_on_validation": threshold,
            "validation_metrics": _metrics(
                labels[validation_mask], validation_scores, threshold
            ),
            "test_metrics": _metrics(labels[test_mask], test_scores, threshold),
            "top_features_by_gain": [
                {"feature": name, "gain": float(gain)}
                for name, gain in ranked_features[:20]
            ],
        }
        pq.write_table(
            pa.table(
                {
                    "row_index": np.where(test_mask)[0].astype(np.int64),
                    "rotation_fold": np.full(test_mask.sum(), rotation_fold, dtype=np.int8),
                    "test_fold": np.full(test_mask.sum(), test_fold, dtype=np.int8),
                    "country": raw_countries[test_mask],
                    "label": labels[test_mask],
                    "score": test_scores.astype(np.float32),
                    "predicted": (test_scores >= threshold).astype(np.int8),
                }
            ),
            prediction_path,
            compression="zstd",
        )
        results = [row for row in results if int(row["rotation_fold"]) != rotation_fold]
        results.append(result)
        results.sort(key=lambda row: int(row["rotation_fold"]))
        results_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        del (
            train_x,
            validation_x,
            test_x,
            train_y,
            model,
            calibrator,
            validation_raw_scores,
            validation_scores,
            test_raw_scores,
            test_scores,
        )

    status = "READY" if len(results) == N_SPLITS else "PARTIAL"
    report = {
        "status": status,
        "benchmark": "V4FinBench",
        "paper_horizon": 1,
        "model": "lightgbm_fixed",
        "fold_protocol": "official country-preserving company-grouped five-fold rotation",
        "target": "main_label",
        "probability_calibration": "Platt scaling on each validation fold",
        "test_label_used_during_training_or_threshold_selection": False,
        "feature_count": len(feature_names),
        "completed_folds": [int(row["rotation_fold"]) for row in results],
        "fold_results": results,
        "summary": _summary(results),
    }
    (output_root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# V4FinBench A2 非线性表格基线",
        "",
        f"- 状态：`{status}`；",
        f"- 已完成折：{report['completed_folds']}；",
        "- 模型：LightGBM（公开基线搜索空间中的固定参数，不逐折调参）；",
        "- 概率校准和F1阈值只使用验证折；",
        "- 测试标签未用于训练、预处理、校准或阈值选择。",
        "",
        "| 指标 | 均值 | 标准差 |",
        "|---|---:|---:|",
    ]
    for name, value in report["summary"].items():
        lines.append(f"| {name} | {value['mean']:.6f} | {value['std']:.6f} |")
    (output_root / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run V4FinBench A2 LightGBM baseline")
    parser.add_argument(
        "--data",
        default="/artifacts/agent_benchmarks/v4finbench_h1_v1/company_years_h2.parquet",
    )
    parser.add_argument(
        "--folds",
        default="/artifacts/agent_benchmarks/v4finbench_h1_v1/folds/fold_assignments.parquet",
    )
    parser.add_argument(
        "--output-root",
        default="/artifacts/agent_benchmarks/v4finbench_h1_v1/lightgbm_baseline",
    )
    parser.add_argument("--fold", default="all")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    selected = list(range(N_SPLITS)) if args.fold == "all" else [int(args.fold)]
    if any(fold not in range(N_SPLITS) for fold in selected):
        raise ValueError("fold must be all or an integer from 0 to 4")
    report = run_lightgbm_baseline(
        data_path=Path(args.data),
        folds_path=Path(args.folds),
        output_root=Path(args.output_root),
        selected_folds=selected,
        resume=args.resume,
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
