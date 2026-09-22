from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler


COLUMNS_TO_DROP = {
    "company",
    "industry",
    "link",
    "num",
    "emis_id",
    "sector_2",
    "sector_3",
    "sector_4",
    "Revenue/employee",
    "Fixed_assets/employee",
    "EBITDA/cash_flow",
    "main_label",
}
N_SPLITS = 5


def _numeric_features(schema: pa.Schema) -> list[str]:
    return [
        field.name
        for field in schema
        if field.name not in COLUMNS_TO_DROP
        and (
            pa.types.is_integer(field.type)
            or pa.types.is_floating(field.type)
            or pa.types.is_boolean(field.type)
        )
    ]


def _replace_nonfinite_and_impute(
    train: np.ndarray, validation: np.ndarray, test: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    for values in (train, validation, test):
        values[~np.isfinite(values)] = np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        medians = np.nanmedian(train, axis=0)
    all_nan_training_features = int((~np.isfinite(medians)).sum())
    medians = np.where(np.isfinite(medians), medians, 0.0).astype(np.float32)
    for values in (train, validation, test):
        for column in range(values.shape[1]):
            missing = np.isnan(values[:, column])
            if missing.any():
                values[missing, column] = medians[column]
    scaler = StandardScaler(copy=False)
    train = scaler.fit_transform(train).astype(np.float32, copy=False)
    validation = scaler.transform(validation).astype(np.float32, copy=False)
    test = scaler.transform(test).astype(np.float32, copy=False)
    return train, validation, test, all_nan_training_features


def _best_f1_threshold(labels: np.ndarray, scores: np.ndarray) -> float:
    precision, recall, thresholds = precision_recall_curve(labels, scores)
    if not len(thresholds):
        return 0.5
    f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(
        precision[:-1] + recall[:-1], 1e-12
    )
    return float(thresholds[int(np.nanargmax(f1))])


def _score_logit(scores: np.ndarray) -> np.ndarray:
    clipped = np.clip(scores, 1e-7, 1 - 1e-7)
    return np.log(clipped / (1 - clipped)).reshape(-1, 1)


def _fit_platt_calibrator(
    labels: np.ndarray, scores: np.ndarray
) -> LogisticRegression:
    calibrator = LogisticRegression(C=1_000_000, max_iter=200, solver="lbfgs")
    calibrator.fit(_score_logit(scores), labels)
    return calibrator


def _calibrate(calibrator: LogisticRegression, scores: np.ndarray) -> np.ndarray:
    return calibrator.predict_proba(_score_logit(scores))[:, 1]


def _ece(labels: np.ndarray, scores: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = len(labels)
    value = 0.0
    for index in range(bins):
        if index == bins - 1:
            selected = (scores >= edges[index]) & (scores <= edges[index + 1])
        else:
            selected = (scores >= edges[index]) & (scores < edges[index + 1])
        if selected.any():
            value += selected.mean() * abs(scores[selected].mean() - labels[selected].mean())
    return float(value if total else 0.0)


def _operating_points(labels: np.ndarray, scores: np.ndarray) -> dict[str, float]:
    precision, recall, _ = precision_recall_curve(labels, scores)
    result: dict[str, float] = {}
    for target in (0.05, 0.10, 0.25, 0.50):
        eligible = recall[precision >= target]
        result[f"recall_at_precision_{int(target * 100)}"] = (
            float(eligible.max()) if len(eligible) else 0.0
        )
    for target in (0.50, 0.75, 0.90):
        eligible = precision[recall >= target]
        result[f"precision_at_recall_{int(target * 100)}"] = (
            float(eligible.max()) if len(eligible) else 0.0
        )
    return result


def _metrics(labels: np.ndarray, scores: np.ndarray, threshold: float) -> dict[str, float]:
    predicted = (scores >= threshold).astype(np.int8)
    return {
        "pr_auc": float(average_precision_score(labels, scores)),
        "roc_auc": float(roc_auc_score(labels, scores)),
        "f1": float(f1_score(labels, predicted, zero_division=0)),
        "precision": float(precision_score(labels, predicted, zero_division=0)),
        "recall": float(recall_score(labels, predicted, zero_division=0)),
        "brier": float(brier_score_loss(labels, scores)),
        "ece_10": _ece(labels, scores),
        **_operating_points(labels, scores),
    }


def _summary(results: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    metric_names = list(results[0]["test_metrics"])
    return {
        name: {
            "mean": float(np.mean([row["test_metrics"][name] for row in results])),
            "std": float(np.std([row["test_metrics"][name] for row in results])),
        }
        for name in metric_names
    }


def run_logistic_baseline(
    *,
    data_path: Path,
    folds_path: Path,
    output_root: Path,
    selected_folds: list[int],
    resume: bool,
) -> dict[str, Any]:
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
            _replace_nonfinite_and_impute(
                train_x, validation_x, test_x
            )
        )
        model = LogisticRegression(
            C=0.1,
            class_weight="balanced",
            max_iter=300,
            random_state=42,
            solver="lbfgs",
        )
        model.fit(train_x, labels[train_mask])
        validation_raw_scores = model.predict_proba(validation_x)[:, 1]
        calibrator = _fit_platt_calibrator(
            labels[validation_mask], validation_raw_scores
        )
        validation_scores = _calibrate(calibrator, validation_raw_scores)
        threshold = _best_f1_threshold(labels[validation_mask], validation_scores)
        test_raw_scores = model.predict_proba(test_x)[:, 1]
        test_scores = _calibrate(calibrator, test_raw_scores)
        result = {
            "model": "class_weighted_logistic_regression",
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
            "train_positives": int(labels[train_mask].sum()),
            "validation_positives": int(labels[validation_mask].sum()),
            "test_positives": int(labels[test_mask].sum()),
            "feature_count": len(feature_names),
            "all_nan_training_features": all_nan_training_features,
            "probability_calibration": "Platt scaling fitted on validation fold",
            "calibration_coefficient": float(calibrator.coef_[0, 0]),
            "calibration_intercept": float(calibrator.intercept_[0]),
            "threshold_selected_on_validation": threshold,
            "validation_metrics": _metrics(
                labels[validation_mask], validation_scores, threshold
            ),
            "test_metrics": _metrics(labels[test_mask], test_scores, threshold),
            "iterations": int(model.n_iter_[0]),
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
        "model": "class_weighted_logistic_regression",
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
    metric_rows = [
        "# V4FinBench A1 统计基线",
        "",
        f"- 状态：`{status}`；",
        f"- 已完成折：{report['completed_folds']}；",
        "- 模型：类别加权 Logistic Regression；",
        "- 阈值：仅在每轮验证折按最佳 F1 选择；",
        "- 测试标签未用于训练、预处理或阈值选择。",
        "",
        "| 指标 | 均值 | 标准差 |",
        "|---|---:|---:|",
    ]
    for name, value in report["summary"].items():
        metric_rows.append(f"| {name} | {value['mean']:.6f} | {value['std']:.6f} |")
    (output_root / "report.md").write_text("\n".join(metric_rows) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run V4FinBench A1 logistic baseline")
    parser.add_argument(
        "--data",
        default="/artifacts/phase5_step02/v4finbench_h1_v1/company_years_h2.parquet",
    )
    parser.add_argument(
        "--folds",
        default="/artifacts/phase5_step02/v4finbench_h1_v1/folds/fold_assignments.parquet",
    )
    parser.add_argument(
        "--output-root",
        default="/artifacts/phase5_step02/v4finbench_h1_v1/logistic_baseline",
    )
    parser.add_argument("--fold", default="all")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    selected = list(range(N_SPLITS)) if args.fold == "all" else [int(args.fold)]
    if any(fold not in range(N_SPLITS) for fold in selected):
        raise ValueError("fold must be all or an integer from 0 to 4")
    report = run_logistic_baseline(
        data_path=Path(args.data),
        folds_path=Path(args.folds),
        output_root=Path(args.output_root),
        selected_folds=selected,
        resume=args.resume,
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
