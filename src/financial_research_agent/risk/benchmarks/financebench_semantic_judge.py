from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from financial_research_agent.config import get_settings
from financial_research_agent.providers.model import build_model_provider


class FinanceBenchJudgment(BaseModel):
    verdict: Literal["CORRECT", "INCORRECT"]
    reason: str = Field(min_length=1, max_length=1200)
    essential_answer_present: bool
    contradiction_present: bool


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def judge_financebench(
    *,
    predictions_path: Path,
    benchmark_root: Path,
    output_root: Path,
    limit: int | None,
) -> dict[str, Any]:
    predictions = _read_jsonl(predictions_path)
    if limit is not None:
        predictions = predictions[:limit]
    if not predictions or any(row["benchmark"] != "financebench" for row in predictions):
        raise ValueError("FinanceBench predictions are required")
    split = str(predictions[0]["split"])
    inputs = {
        str(row["case_id"]): row
        for row in _read_jsonl(
            benchmark_root / "inputs" / "financebench" / f"{split}.jsonl"
        )
    }
    references = {
        str(row["case_id"]): row
        for row in _read_jsonl(
            benchmark_root / "gold" / "financebench" / f"{split}.jsonl"
        )
    }
    provider = build_model_provider(get_settings())
    judgments: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    try:
        for result in predictions:
            case_id = str(result["case_id"])
            try:
                response = await provider.create_structured_response(
                    instruction=(
                        "Judge whether a predicted FinanceBench answer is substantively correct "
                        "relative to the public reference answer. This is evaluation after "
                        "inference, not answer generation. Accept equivalent wording, reasonable "
                        "rounding, correct unit conversion, and a concise entity answer when the "
                        "question asks which entity; supporting details in the reference need not "
                        "all be repeated unless they are essential to the conclusion. Mark "
                        "INCORRECT for a wrong conclusion, contradiction, refusal when the answer "
                        "is available, or omission of an essential requested quantity or condition. "
                        "Do not reward the explanation when the final answer contradicts it."
                    ),
                    input_payload={
                        "case_id": case_id,
                        "question": inputs[case_id]["question"],
                        "reference_answer": references[case_id]["answer"],
                        "predicted_answer": result["prediction"].get("answer", ""),
                        "predicted_scale": result["prediction"].get("scale", ""),
                        "predicted_explanation": result["prediction"].get(
                            "explanation", ""
                        ),
                    },
                    schema=FinanceBenchJudgment,
                    max_tokens=700,
                    operation="financebench_semantic_judge",
                )
                judgment = FinanceBenchJudgment.model_validate(response.content)
                judgments.append(
                    {
                        "case_id": case_id,
                        "verdict": judgment.verdict,
                        "reason": judgment.reason,
                        "essential_answer_present": judgment.essential_answer_present,
                        "contradiction_present": judgment.contradiction_present,
                        "usage": response.usage.model_dump(mode="json"),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - evaluation failure is a scored failure
                failures.append(
                    {
                        "case_id": case_id,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "raw_output": str(getattr(exc, "raw_output", "")),
                    }
                )
    finally:
        await provider.aclose()

    output_root.mkdir(parents=True, exist_ok=True)
    correct = sum(row["verdict"] == "CORRECT" for row in judgments)
    total = len(predictions)
    report = {
        "status": "PASS" if not failures else "PARTIAL",
        "benchmark": "financebench",
        "split": split,
        "candidate_model": predictions[0]["model"],
        "judge_model": get_settings().model_name,
        "judge_policy": "reference-aware semantic judge after inference",
        "same_model_judge_limitation": (
            predictions[0]["model"] == get_settings().model_name
        ),
        "gold_used_during_inference": False,
        "case_count": total,
        "judged_cases": len(judgments),
        "judge_failures": len(failures),
        "semantic_accuracy_failures_as_zero": correct / total if total else None,
        "judgments": judgments,
        "failures": failures,
    }
    (output_root / "semantic_score.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# FinanceBench 语义评分",
        "",
        f"- 候选模型：`{report['candidate_model']}`",
        f"- Judge：`{report['judge_model']}`",
        f"- 题数：{total}",
        f"- 语义正确率（Judge失败计0）：{report['semantic_accuracy_failures_as_zero']:.1%}",
        "- Gold 仅在推理完成后的评分阶段读取。",
        "- 限制：当前候选与 Judge 使用同一模型，只可作为开发回归信号，不能视为人工复核。",
        "",
    ]
    for row in judgments:
        lines.extend(
            [
                f"## {row['case_id']} — {row['verdict']}",
                "",
                row["reason"],
                "",
            ]
        )
    (output_root / "semantic_score.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Judge FinanceBench answer semantics")
    parser.add_argument("--predictions", required=True)
    parser.add_argument(
        "--benchmark-root", default="/artifacts/risk_data/public_benchmarks_v1"
    )
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    report = asyncio.run(
        judge_financebench(
            predictions_path=Path(args.predictions),
            benchmark_root=Path(args.benchmark_root),
            output_root=Path(args.output_root),
            limit=args.limit,
        )
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
