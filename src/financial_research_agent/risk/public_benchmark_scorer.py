from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _program_tokens(program: str) -> list[str]:
    tokens: list[str] = []
    for raw in program.split(", "):
        current = ""
        for character in raw:
            if character == ")" and current:
                tokens.append(current)
                current = ""
            current += character
            if character in {"(", ")"}:
                tokens.append(current)
                current = ""
        if current:
            tokens.append(current)
    return [*tokens, "EOF"]


def _run(command: list[str], *, cwd: Path) -> str:
    result = subprocess.run(  # noqa: S603 - fixed local official evaluator scripts
        command,
        cwd=cwd,
        check=False,
        text=True,
        capture_output=True,
        timeout=300,
    )
    output = (result.stdout + "\n" + result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError(f"official evaluator failed ({result.returncode}): {output}")
    return output


def _numeric_values(value: Any) -> list[float]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    values: list[float] = []
    for raw in re.findall(r"(?<![A-Za-z])[-+]?\$?\d[\d,]*(?:\.\d+)?%?", text):
        normalized = raw.replace("$", "").replace(",", "")
        percent = normalized.endswith("%")
        if percent:
            normalized = normalized[:-1]
        try:
            number = float(normalized)
        except ValueError:
            continue
        values.append(number / 100 if percent else number)
    return values


def _numeric_alternatives(value: Any) -> list[set[float]]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    alternatives: list[set[float]] = []
    for raw in re.findall(r"(?<![A-Za-z])[-+]?\$?\d[\d,]*(?:\.\d+)?%?", text):
        normalized = raw.replace("$", "").replace(",", "")
        percent = normalized.endswith("%")
        if percent:
            normalized = normalized[:-1]
        try:
            number = float(normalized)
        except ValueError:
            continue
        alternatives.append({number, number / 100} if percent else {number})
    return alternatives


def _normalized_text(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return re.sub(r"[^0-9a-z]+", " ", text.lower()).strip()


def _financebench_score(
    predictions: list[dict[str, Any]], gold_path: Path
) -> dict[str, Any]:
    gold = {str(row["case_id"]): row for row in _read_jsonl(gold_path)}
    details: list[dict[str, Any]] = []
    numeric_cases = 0
    numeric_correct = 0
    exact_text_correct = 0
    evidence_recall_total = 0.0
    evidence_precision_total = 0.0
    for result in predictions:
        case_id = str(result["case_id"])
        reference = gold[case_id]
        prediction = result["prediction"]
        predicted_answer = prediction.get("answer", "")
        gold_answer = reference.get("answer", "")
        predicted_groups = _numeric_alternatives(predicted_answer)
        gold_groups = _numeric_alternatives(gold_answer)
        numeric_match = False
        if gold_groups:
            numeric_cases += 1
            numeric_match = all(
                any(
                    abs(predicted - expected)
                    <= max(1e-6, abs(expected) * 0.025)
                    for predicted_group in predicted_groups
                    for predicted in predicted_group
                    for expected in expected_group
                )
                for expected_group in gold_groups
            )
            numeric_correct += int(numeric_match)
        text_match = _normalized_text(predicted_answer) == _normalized_text(gold_answer)
        exact_text_correct += int(text_match)

        predicted_pages = {int(page) - 1 for page in prediction.get("evidence_pages", [])}
        gold_pages = {
            int(item["evidence_page_num"])
            for item in reference.get("evidence", [])
            if item.get("evidence_page_num") is not None
        }
        overlap = predicted_pages & gold_pages
        recall = len(overlap) / len(gold_pages) if gold_pages else 1.0
        precision = len(overlap) / len(predicted_pages) if predicted_pages else 0.0
        evidence_recall_total += recall
        evidence_precision_total += precision
        details.append(
            {
                "case_id": case_id,
                "numeric_match": numeric_match,
                "exact_text_match": text_match,
                "evidence_recall": recall,
                "evidence_precision": precision,
                "semantic_review_required": not numeric_match and not text_match,
            }
        )
    count = len(predictions)
    return {
        "scoring_policy": "deterministic numeric/text plus official gold evidence; no LLM judge",
        "case_count": count,
        "numeric_case_count": numeric_cases,
        "numeric_accuracy": numeric_correct / numeric_cases if numeric_cases else None,
        "exact_text_accuracy": exact_text_correct / count if count else None,
        "evidence_recall": evidence_recall_total / count if count else None,
        "evidence_precision": evidence_precision_total / count if count else None,
        "details": details,
    }


def _finqa_score(
    predictions: list[dict[str, Any]], benchmark_root: Path, split: str, output_root: Path
) -> dict[str, Any]:
    raw = json.loads(
        (benchmark_root / "raw" / "finqa" / f"{split}.json").read_text(encoding="utf-8")
    )
    selected_ids = {str(row["case_id"]) for row in predictions}
    selected_gold = [row for row in raw if str(row["id"]) in selected_ids]
    prediction_rows = []
    for row in predictions:
        program = row["prediction"].get("program")
        if not program:
            program = "invalid(0, 0)"
        prediction_rows.append(
            {"id": row["case_id"], "predicted": _program_tokens(str(program))}
        )
    gold_path = output_root / "finqa_gold.json"
    prediction_path = output_root / "finqa_predictions.json"
    gold_path.write_text(json.dumps(selected_gold, ensure_ascii=False), encoding="utf-8")
    prediction_path.write_text(json.dumps(prediction_rows, ensure_ascii=False), encoding="utf-8")
    evaluator = benchmark_root / "official_evaluators" / "finqa" / "evaluate.py"
    output = _run([sys.executable, str(evaluator), str(prediction_path), str(gold_path)], cwd=evaluator.parent)
    execution = re.search(r"Exe acc:\s+([0-9.]+)", output)
    program = re.search(r"Prog acc:\s+([0-9.]+)", output)
    return {
        "scoring_policy": "official FinQA evaluator",
        "case_count": len(predictions),
        "execution_accuracy": float(execution.group(1)) if execution else None,
        "program_accuracy": float(program.group(1)) if program else None,
        "official_output": output,
    }


def _tatqa_score(
    predictions: list[dict[str, Any]], benchmark_root: Path, split: str, output_root: Path
) -> dict[str, Any]:
    raw = json.loads(
        (benchmark_root / "raw" / "tatqa" / f"{split}.json").read_text(encoding="utf-8")
    )
    selected_ids = {str(row["case_id"]) for row in predictions}
    selected_gold: list[dict[str, Any]] = []
    for document in raw:
        questions = [
            question
            for question in document.get("questions", [])
            if str(question.get("uid") or question.get("id")) in selected_ids
        ]
        if questions:
            selected_gold.append({**document, "questions": questions})
    prediction_rows = {
        str(row["case_id"]): [
            row["prediction"].get("answer", ""),
            row["prediction"].get("scale", ""),
        ]
        for row in predictions
    }
    gold_path = output_root / "tatqa_gold.json"
    prediction_path = output_root / "tatqa_predictions.json"
    gold_path.write_text(json.dumps(selected_gold, ensure_ascii=False), encoding="utf-8")
    prediction_path.write_text(json.dumps(prediction_rows, ensure_ascii=False), encoding="utf-8")
    evaluator = benchmark_root / "official_evaluators" / "tatqa" / "tatqa_eval.py"
    output = _run(
        [
            sys.executable,
            str(evaluator),
            "--gold_path",
            str(gold_path),
            "--pred_path",
            str(prediction_path),
        ],
        cwd=evaluator.parent,
    )
    exact_match = re.search(r"Exact-match accuracy\s+([0-9.]+)", output)
    f1 = re.search(r"F1 score\s+([0-9.]+)", output)
    return {
        "scoring_policy": "official TAT-QA evaluator",
        "case_count": len(predictions),
        "exact_match": float(exact_match.group(1)) if exact_match else None,
        "f1": float(f1.group(1)) if f1 else None,
        "official_output": output,
    }


def score_public_predictions(
    *,
    predictions_path: Path,
    benchmark_root: Path,
    output_root: Path,
    failures_path: Path | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    predictions = _read_jsonl(predictions_path)
    if limit is not None:
        predictions = predictions[:limit]
    if not predictions:
        raise ValueError("prediction file is empty")
    failures = (
        _read_jsonl(failures_path)
        if failures_path is not None and failures_path.exists()
        else []
    )
    benchmark = str(predictions[0]["benchmark"])
    split = str(predictions[0]["split"])
    if any(row["benchmark"] != benchmark or row["split"] != split for row in predictions):
        raise ValueError("prediction file mixes benchmarks or splits")
    for failure in failures:
        if failure["benchmark"] != benchmark or failure["split"] != split:
            raise ValueError("failure file mixes benchmarks or splits")
        predictions.append(
            {
                "benchmark": benchmark,
                "split": split,
                "case_id": failure["case_id"],
                "mode": failure["mode"],
                "model": failure["model"],
                "prediction": {
                    "answer": "",
                    "scale": "",
                    "program": None,
                    "evidence_pages": [],
                    "explanation": "",
                },
            }
        )
    output_root.mkdir(parents=True, exist_ok=True)
    if benchmark == "financebench":
        metrics = _financebench_score(
            predictions,
            benchmark_root / "gold" / "financebench" / f"{split}.jsonl",
        )
    elif benchmark == "finqa":
        metrics = _finqa_score(predictions, benchmark_root, split, output_root)
    elif benchmark == "tatqa":
        metrics = _tatqa_score(predictions, benchmark_root, split, output_root)
    else:
        raise ValueError(f"unsupported benchmark: {benchmark}")
    report = {
        "status": "SCORED",
        "benchmark": benchmark,
        "split": split,
        "mode": predictions[0]["mode"],
        "model": predictions[0]["model"],
        "inference_successful_cases": len(predictions) - len(failures),
        "inference_failed_cases": len(failures),
        "inference_success_rate": (len(predictions) - len(failures)) / len(predictions),
        "metrics": metrics,
    }
    report_path = output_root / "score.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Score public benchmark predictions")
    parser.add_argument("--predictions", required=True)
    parser.add_argument(
        "--benchmark-root", default="/artifacts/phase5_step01/public_benchmarks_v1"
    )
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--failures")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    report = score_public_predictions(
        predictions_path=Path(args.predictions),
        benchmark_root=Path(args.benchmark_root),
        output_root=Path(args.output_root),
        failures_path=Path(args.failures) if args.failures else None,
        limit=args.limit,
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
