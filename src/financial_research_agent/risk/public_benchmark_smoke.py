from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


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
        timeout=180,
    )
    output = (result.stdout + "\n" + result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError(f"official evaluator failed ({result.returncode}): {output}")
    return output


def _financebench_smoke(root: Path, sample_size: int) -> dict[str, Any]:
    path = root / "raw" / "financebench" / "open_source.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    sample = rows[:sample_size]
    answer_passed = sum(bool(row.get("answer")) for row in sample)
    evidence_passed = sum(bool(row.get("evidence")) for row in sample)
    passed = len(sample) == sample_size and answer_passed == sample_size and evidence_passed == sample_size
    return {
        "status": "PASS" if passed else "FAIL",
        "sample_size": len(sample),
        "gold_answer_schema_passed": answer_passed,
        "gold_evidence_schema_passed": evidence_passed,
        "note": "FinanceBench publishes gold answer/evidence but no official deterministic scoring script; this is a schema-only scorer entry check.",
    }


def _finqa_smoke(root: Path, output_root: Path, sample_size: int) -> dict[str, Any]:
    raw = json.loads((root / "raw" / "finqa" / "test.json").read_text(encoding="utf-8"))
    sample = raw[:sample_size]
    predictions = [
        {"id": item["id"], "predicted": _program_tokens(item["qa"]["program"])}
        for item in sample
    ]
    gold_path = output_root / "finqa_gold_sample.json"
    prediction_path = output_root / "finqa_oracle_predictions.json"
    gold_path.write_text(json.dumps(sample, ensure_ascii=False), encoding="utf-8")
    prediction_path.write_text(json.dumps(predictions, ensure_ascii=False), encoding="utf-8")
    evaluator = root / "official_evaluators" / "finqa" / "evaluate.py"
    output = _run([sys.executable, str(evaluator), str(prediction_path), str(gold_path)], cwd=evaluator.parent)
    passed = bool(re.search(r"Exe acc:\s+1\.0", output) and re.search(r"Prog acc:\s+1\.0", output))
    return {
        "status": "PASS" if passed else "FAIL",
        "sample_size": len(sample),
        "official_evaluator_output": output,
        "note": "Oracle predictions validate the official scorer only; this is not an Agent performance result.",
    }


def _tatqa_smoke(root: Path, output_root: Path, sample_size: int) -> dict[str, Any]:
    raw = json.loads((root / "raw" / "tatqa" / "test.json").read_text(encoding="utf-8"))
    selected_documents: list[dict[str, Any]] = []
    predictions: dict[str, list[Any]] = {}
    count = 0
    for document in raw:
        selected_questions = []
        for question in document.get("questions", []):
            if count >= sample_size:
                break
            selected_questions.append(question)
            predictions[str(question["uid"])] = [question["answer"], question.get("scale", "")]
            count += 1
        if selected_questions:
            selected_documents.append({**document, "questions": selected_questions})
        if count >= sample_size:
            break
    gold_path = output_root / "tatqa_gold_sample.json"
    prediction_path = output_root / "tatqa_oracle_predictions.json"
    gold_path.write_text(json.dumps(selected_documents, ensure_ascii=False), encoding="utf-8")
    prediction_path.write_text(json.dumps(predictions, ensure_ascii=False), encoding="utf-8")
    evaluator = root / "official_evaluators" / "tatqa" / "tatqa_eval.py"
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
    passed = "Exact-match accuracy 100.00" in output and "F1 score 100.00" in output
    return {
        "status": "PASS" if passed else "FAIL",
        "sample_size": count,
        "official_evaluator_output": output,
        "note": "Oracle predictions validate the official scorer only; this is not an Agent performance result.",
    }


def run_smoke(root: Path, *, output_root: Path, sample_size: int = 5) -> tuple[Path, Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    results = {
        "financebench": _financebench_smoke(root, sample_size),
        "finqa": _finqa_smoke(root, output_root, sample_size),
        "tatqa": _tatqa_smoke(root, output_root, sample_size),
    }
    passed = all(item["status"] == "PASS" for item in results.values())
    report = {
        "status": "PASS" if passed else "FAIL",
        "purpose": "public benchmark scorer entry smoke test",
        "agent_performance_result": False,
        "results": results,
    }
    json_path = output_root / "report.json"
    markdown_path = output_root / "report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 公开 Benchmark 评分入口最小验证",
        "",
        f"- 状态：`{report['status']}`",
        "- 使用少量Gold生成的Oracle预测验证评分器；不代表Agent效果。",
        "",
        "| 数据集 | 样本 | 结果 |",
        "|---|---:|---|",
    ]
    for name, result in results.items():
        lines.append(f"| {name} | {result['sample_size']} | {result['status']} |")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test official benchmark scorers")
    parser.add_argument("--root", default="/artifacts/phase5_step01/public_benchmarks_v1")
    parser.add_argument(
        "--output-root", default="/artifacts/phase5_step01/public_benchmark_scorers_v1"
    )
    parser.add_argument("--sample-size", type=int, default=5)
    args = parser.parse_args()
    paths = run_smoke(
        Path(args.root), output_root=Path(args.output_root), sample_size=args.sample_size
    )
    print(json.dumps({"json": str(paths[0]), "markdown": str(paths[1])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
