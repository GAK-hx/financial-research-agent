from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.calibration import calibration_curve
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from financial_research_agent.risk.domain.registry import RiskMetricRegistry

BASELINE_VERSION = "issuer-risk-baseline-v1"
RECENT_START_PERIOD = pd.Timestamp("2016-12-31")
FIXED_TEST_START_PERIOD = pd.Timestamp("2023-12-31")
FEATURE_COLUMNS = [
    "current_ratio",
    "cash_to_short_debt",
    "ocf_to_current_liabilities",
    "ocf_to_net_profit",
    "accruals_to_assets",
    "profit_cashflow_divergence",
    "receivables_revenue_growth_gap",
    "inventory_revenue_growth_gap",
    "goodwill_to_assets",
    "impairment_to_assets",
    "nonstandard_audit_opinion",
]


def expected_calibration_error(
    labels: np.ndarray, probabilities: np.ndarray, *, bins: int = 5
) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = len(labels)
    score = 0.0
    for index in range(bins):
        lower, upper = edges[index], edges[index + 1]
        mask = (probabilities >= lower) & (
            probabilities <= upper if index == bins - 1 else probabilities < upper
        )
        if not mask.any():
            continue
        score += mask.mean() * abs(labels[mask].mean() - probabilities[mask].mean())
    return float(score) if total else float("nan")


def _metrics(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, float]:
    predictions = (probabilities >= 0.5).astype(int)
    return {
        "precision": float(precision_score(labels, predictions, zero_division=0)),
        "recall": float(recall_score(labels, predictions, zero_division=0)),
        "f1": float(f1_score(labels, predictions, zero_division=0)),
        "pr_auc": float(average_precision_score(labels, probabilities)),
        "brier": float(brier_score_loss(labels, probabilities)),
        "ece_5_bins": expected_calibration_error(labels, probabilities, bins=5),
    }


def _next_period_proxy(frame: pd.DataFrame) -> pd.Series:
    severe = (
        (frame["nonstandard_audit_opinion"].fillna(0) >= 1)
        | (frame["current_ratio"].fillna(np.inf) < 0.8)
        | (frame["ocf_to_current_liabilities"].fillna(np.inf) < 0)
        | (frame["impairment_to_assets"].fillna(-np.inf) > 0.05)
        | (frame["profit_cashflow_divergence"].fillna(-np.inf) >= 3)
    )
    return severe.groupby(frame["issuer_id"]).shift(-1)


def _rule_probability(frame: pd.DataFrame) -> pd.Series:
    definitions = [
        item for item in RiskMetricRegistry.load_default().all()
        if item.code in FEATURE_COLUMNS
    ]
    scores = []
    for row in frame.itertuples(index=False):
        score = 0.0
        for definition in definitions:
            value = getattr(row, definition.code)
            if pd.isna(value):
                continue
            for threshold in definition.thresholds:
                matched = {
                    "lt": value < threshold.value,
                    "le": value <= threshold.value,
                    "gt": value > threshold.value,
                    "ge": value >= threshold.value,
                    "eq": value == threshold.value,
                }[threshold.operator]
                if matched:
                    score = max(score, 1.0 if threshold.status == "escalate" else 0.5)
        scores.append(score)
    return pd.Series(scores, index=frame.index, dtype=float)


def _build_dataset(features: pd.DataFrame) -> pd.DataFrame:
    present = features.copy()
    present.loc[present["availability"] != "present", "value"] = np.nan
    wide = present.pivot_table(
        index=["issuer_id", "report_period"],
        columns="metric_code",
        values="value",
        aggfunc="first",
        dropna=False,
    ).reset_index()
    for column in FEATURE_COLUMNS:
        if column not in wide:
            wide[column] = np.nan
    wide.sort_values(["issuer_id", "report_period"], inplace=True)
    wide["proxy_label"] = _next_period_proxy(wide)
    wide["rule_probability"] = _rule_probability(wide)
    dataset = wide
    dataset = dataset[dataset["proxy_label"].notna()].copy()
    dataset["proxy_label"] = dataset["proxy_label"].astype(int)
    dataset["report_period"] = pd.to_datetime(dataset["report_period"])
    return dataset


def _bootstrap_ci(
    labels: np.ndarray,
    probabilities: np.ndarray,
    *,
    repeats: int = 500,
    seed: int = 20260907,
) -> dict[str, list[float]]:
    generator = np.random.default_rng(seed)
    samples: dict[str, list[float]] = {name: [] for name in ("precision", "recall", "f1", "pr_auc")}
    for _ in range(repeats):
        indices = generator.integers(0, len(labels), size=len(labels))
        sampled_labels = labels[indices]
        if len(np.unique(sampled_labels)) < 2:
            continue
        result = _metrics(sampled_labels, probabilities[indices])
        for name in samples:
            samples[name].append(result[name])
    return {
        name: [float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))]
        for name, values in samples.items()
        if values
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 规则与逻辑回归基线",
        "",
        f"- 样本：{report['sample_count']}（训练 {report['train_count']} / 测试 {report['test_count']}）",
        f"- 时间切分：测试集从 `{report['test_start_period']}` 开始",
        f"- Proxy 正例率：{report['test_positive_rate']:.2%}",
        "",
        "| 基线 | Precision | Recall | F1 | PR-AUC | Brier | ECE |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, result in report["baselines"].items():
        lines.append(
            f"| {name} | {result['precision']:.4f} | {result['recall']:.4f} | "
            f"{result['f1']:.4f} | {result['pr_auc']:.4f} | {result['brier']:.4f} | "
            f"{result['ece_5_bins']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "本报告的标签是下一报告期严重财务信号的程序化 Proxy，不是人工 Gold，也不证明投资预测能力。",
            "规则与逻辑回归只用同一批当期财务/审计特征，不读取报告期后发生的更正或问询事件；",
            "当前数据源只提供当前修订快照，历史 Point-in-Time 预测分数必须等原始历史快照/PDF复核后再发布；",
            "这里的作用是冻结可运行、可比较的规则与统计基线管线。",
        ]
    )
    return "\n".join(lines)


def run_baselines(root: Path, *, feature_root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    features = pq.read_table(feature_root / "risk_features.parquet").to_pandas()
    dataset = _build_dataset(features)
    dataset = dataset[dataset["report_period"] >= RECENT_START_PERIOD].copy()
    split_period = FIXED_TEST_START_PERIOD
    train = dataset[dataset["report_period"] < split_period].copy()
    test = dataset[dataset["report_period"] >= split_period].copy()
    if train["proxy_label"].nunique() < 2 or test["proxy_label"].nunique() < 2:
        raise ValueError("time split must contain both proxy classes in train and test")
    pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scaler", StandardScaler()),
            (
                "classifier",
                LogisticRegression(
                    class_weight="balanced", max_iter=2000, random_state=20260907
                ),
            ),
        ]
    )
    pipeline.fit(train[FEATURE_COLUMNS], train["proxy_label"])
    labels = test["proxy_label"].to_numpy(dtype=int)
    logistic_probabilities = pipeline.predict_proba(test[FEATURE_COLUMNS])[:, 1]
    rule_probabilities = test["rule_probability"].fillna(0.0).to_numpy(dtype=float)
    rule_metrics = _metrics(labels, rule_probabilities)
    logistic_metrics = _metrics(labels, logistic_probabilities)
    rule_metrics["ci_95"] = _bootstrap_ci(labels, rule_probabilities)
    logistic_metrics["ci_95"] = _bootstrap_ci(labels, logistic_probabilities)
    calibration_true, calibration_predicted = calibration_curve(
        labels, logistic_probabilities, n_bins=5, strategy="uniform"
    )
    dataset_path = root / "proxy_baseline_dataset.parquet"
    model_path = root / "logistic_regression.joblib"
    dataset.to_parquet(dataset_path, index=False)
    joblib.dump(pipeline, model_path)
    report = {
        "baseline_version": BASELINE_VERSION,
        "label_type": "next_period_severe_signal_proxy_not_human_gold",
        "sample_count": len(dataset),
        "train_count": len(train),
        "test_count": len(test),
        "test_start_period": pd.Timestamp(split_period).date().isoformat(),
        "recent_start_period": RECENT_START_PERIOD.date().isoformat(),
        "split_policy": "fixed calendar split; train 2016-2022, test 2023-2024",
        "train_positive_rate": float(train["proxy_label"].mean()),
        "test_positive_rate": float(test["proxy_label"].mean()),
        "features": FEATURE_COLUMNS,
        "baselines": {"rule_v1": rule_metrics, "logistic_regression_v1": logistic_metrics},
        "logistic_calibration_curve": {
            "mean_predicted_probability": calibration_predicted.tolist(),
            "fraction_of_positives": calibration_true.tolist(),
        },
        "dataset_path": str(dataset_path),
        "model_path": str(model_path),
        "historical_pit_evaluation": "not_claimed_without_a_public_labeled_dataset",
        "rule_predictor_boundary": (
            "same-period financial and audit features only; retrospective disclosure events excluded"
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    json_path = root / "report.json"
    markdown_path = root / "report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run rule and statistical risk baselines")
    parser.add_argument("--root", default="/artifacts/risk_data/baselines_v1")
    parser.add_argument("--feature-root", default="/artifacts/risk_data/features_v1")
    args = parser.parse_args()
    paths = run_baselines(Path(args.root), feature_root=Path(args.feature_root))
    print(json.dumps({"json": str(paths[0]), "markdown": str(paths[1])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
