from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class SourceFile:
    dataset: str
    split: str
    url: str
    format: str = "json"


SOURCES = (
    SourceFile(
        "financebench",
        "open_source",
        "https://raw.githubusercontent.com/patronus-ai/financebench/main/data/financebench_open_source.jsonl",
        "jsonl",
    ),
    SourceFile(
        "finqa",
        "train",
        "https://raw.githubusercontent.com/czyssrs/FinQA/main/dataset/train.json",
    ),
    SourceFile(
        "finqa",
        "dev",
        "https://raw.githubusercontent.com/czyssrs/FinQA/main/dataset/dev.json",
    ),
    SourceFile(
        "finqa",
        "test",
        "https://raw.githubusercontent.com/czyssrs/FinQA/main/dataset/test.json",
    ),
    SourceFile(
        "tatqa",
        "train",
        "https://raw.githubusercontent.com/NExTplusplus/TAT-QA/master/dataset_raw/tatqa_dataset_train.json",
    ),
    SourceFile(
        "tatqa",
        "dev",
        "https://raw.githubusercontent.com/NExTplusplus/TAT-QA/master/dataset_raw/tatqa_dataset_dev.json",
    ),
    SourceFile(
        "tatqa",
        "test",
        "https://raw.githubusercontent.com/NExTplusplus/TAT-QA/master/dataset_raw/tatqa_dataset_test_gold.json",
    ),
)

EVALUATOR_SOURCES = (
    SourceFile(
        "finqa",
        "evaluate",
        "https://raw.githubusercontent.com/czyssrs/FinQA/main/code/evaluate/evaluate.py",
        "python",
    ),
    SourceFile(
        "tatqa",
        "tatqa_eval",
        "https://raw.githubusercontent.com/NExTplusplus/TAT-QA/master/tatqa_eval.py",
        "python",
    ),
    SourceFile(
        "tatqa",
        "tatqa_metric",
        "https://raw.githubusercontent.com/NExTplusplus/TAT-QA/master/tatqa_metric.py",
        "python",
    ),
    SourceFile(
        "tatqa",
        "tatqa_utils",
        "https://raw.githubusercontent.com/NExTplusplus/TAT-QA/master/tatqa_utils.py",
        "python",
    ),
)

DATASET_METADATA = {
    "financebench": {
        "official_repository": "https://github.com/patronus-ai/financebench",
        "evaluation_role": "financial document retrieval, grounded QA and citation",
        "official_metric_policy": "gold answer/evidence; published evaluation uses human review",
        "license_note": "Review upstream terms before redistributing source PDFs or dataset copies.",
    },
    "finqa": {
        "official_repository": "https://github.com/czyssrs/FinQA",
        "evaluation_role": "financial numerical reasoning and executable programs",
        "official_metric_policy": "execution accuracy and program accuracy",
        "license_note": "MIT repository license; retain upstream attribution.",
    },
    "tatqa": {
        "official_repository": "https://github.com/NExTplusplus/TAT-QA",
        "evaluation_role": "joint table-text financial QA",
        "official_metric_policy": "official exact-match/F1 evaluator and scale handling",
        "license_note": "Dataset is CC BY 4.0; retain attribution.",
    },
}

FORBIDDEN_INPUT_FIELDS = {
    "answer",
    "expected_answer",
    "evidence",
    "gold_inds",
    "program",
    "exe_ans",
    "derivation",
    "facts",
}


def _download(source: SourceFile, path: Path, *, retries: int, refresh: bool) -> None:
    if path.exists() and not refresh:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for attempt in range(1, retries + 1):
        try:
            request = Request(source.url, headers={"User-Agent": "financial-agent-benchmark/1.0"})
            with urlopen(request, timeout=180) as response:  # noqa: S310 - fixed official URLs
                payload = response.read()
            if not payload:
                raise ValueError("empty response")
            path.write_bytes(payload)
            return
        except Exception as exc:  # noqa: BLE001 - source errors are reported with retries
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
            if attempt < retries:
                time.sleep(min(30, 2**attempt))
    raise RuntimeError(f"failed to download {source.url}: {'; '.join(errors)}")


def _load(path: Path, *, format: str) -> list[dict[str, Any]]:
    if format == "jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"expected a JSON list: {path}")
    return data


def _financebench(
    rows: list[dict[str, Any]], split: str
) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    for row in rows:
        case_id = str(row["financebench_id"])
        yield (
            {
                "benchmark": "financebench",
                "case_id": case_id,
                "split": split,
                "question": row["question"],
                "document_refs": [row["doc_name"]],
                "metadata": {
                    "company": row.get("company"),
                    "question_type": row.get("question_type"),
                    "question_reasoning": row.get("question_reasoning"),
                },
            },
            {
                "benchmark": "financebench",
                "case_id": case_id,
                "split": split,
                "answer": row["answer"],
                "evidence": row.get("evidence", []),
                "justification": row.get("justification"),
            },
        )


def _finqa(
    rows: list[dict[str, Any]], split: str
) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    for row in rows:
        qa = row["qa"]
        case_id = str(row["id"])
        yield (
            {
                "benchmark": "finqa",
                "case_id": case_id,
                "split": split,
                "question": qa["question"],
                "context": {
                    "pre_text": row.get("pre_text", []),
                    "table": row.get("table", []),
                    "post_text": row.get("post_text", []),
                },
            },
            {
                "benchmark": "finqa",
                "case_id": case_id,
                "split": split,
                "answer": qa.get("exe_ans"),
                "program": qa.get("program"),
                "gold_inds": qa.get("gold_inds", {}),
                "program_re": qa.get("program_re"),
            },
        )


def _tatqa(
    rows: list[dict[str, Any]], split: str
) -> Iterable[tuple[dict[str, Any], dict[str, Any]]]:
    for document in rows:
        context = {
            "table": document.get("table", {}),
            "paragraphs": document.get("paragraphs", []),
        }
        for question in document.get("questions", []):
            case_id = str(question.get("uid") or question.get("id"))
            if not case_id or case_id == "None":
                raise ValueError("TAT-QA question is missing uid")
            yield (
                {
                    "benchmark": "tatqa",
                    "case_id": case_id,
                    "split": split,
                    "question": question["question"],
                    "context": context,
                },
                {
                    "benchmark": "tatqa",
                    "case_id": case_id,
                    "split": split,
                    "answer": question.get("answer"),
                    "answer_type": question.get("answer_type"),
                    "answer_from": question.get("answer_from"),
                    "scale": question.get("scale", ""),
                    "derivation": question.get("derivation", ""),
                    "facts": question.get("facts", []),
                },
            )


NORMALIZERS = {
    "financebench": _financebench,
    "finqa": _finqa,
    "tatqa": _tatqa,
}


def _write_jsonl(path: Path, rows: list[dict[str, Any]], *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    os.chmod(path, 0o600 if private else 0o644)


def prepare_public_benchmarks(
    root: Path, *, retries: int = 5, refresh: bool = False
) -> tuple[Path, Path]:
    raw_root = root / "raw"
    input_root = root / "inputs"
    gold_root = root / "gold"
    gold_root.mkdir(parents=True, exist_ok=True)
    os.chmod(gold_root, 0o700)
    manifest_datasets: dict[str, dict[str, Any]] = {}
    all_keys: set[tuple[str, str, str]] = set()

    for source in SOURCES:
        extension = "jsonl" if source.format == "jsonl" else "json"
        raw_path = raw_root / source.dataset / f"{source.split}.{extension}"
        _download(source, raw_path, retries=retries, refresh=refresh)
        rows = _load(raw_path, format=source.format)
        input_rows: list[dict[str, Any]] = []
        gold_rows: list[dict[str, Any]] = []
        for input_row, gold_row in NORMALIZERS[source.dataset](rows, source.split):
            leaked = FORBIDDEN_INPUT_FIELDS & set(input_row)
            if leaked:
                raise ValueError(f"gold fields leaked into agent input: {sorted(leaked)}")
            key = (source.dataset, source.split, str(input_row["case_id"]))
            if key in all_keys:
                raise ValueError(f"duplicate benchmark case: {key}")
            all_keys.add(key)
            input_rows.append(input_row)
            gold_rows.append(gold_row)
        if len(input_rows) != len(gold_rows) or not input_rows:
            raise ValueError(f"invalid normalized split: {source.dataset}/{source.split}")
        _write_jsonl(input_root / source.dataset / f"{source.split}.jsonl", input_rows)
        _write_jsonl(
            gold_root / source.dataset / f"{source.split}.jsonl", gold_rows, private=True
        )
        dataset = manifest_datasets.setdefault(
            source.dataset,
            {**DATASET_METADATA[source.dataset], "splits": {}, "case_count": 0},
        )
        dataset["splits"][source.split] = {
            "case_count": len(input_rows),
            "input_path": str(
                (input_root / source.dataset / f"{source.split}.jsonl").relative_to(root)
            ),
            "gold_path": str(
                (gold_root / source.dataset / f"{source.split}.jsonl").relative_to(root)
            ),
            "official_source_url": source.url,
        }
        dataset["case_count"] += len(input_rows)

    manifest = {
        "status": "READY",
        "benchmark_policy": "official public labels and official dataset splits only",
        "agent_gold_access": "denied; inputs and gold are stored separately",
        "datasets": manifest_datasets,
        "total_case_count": sum(item["case_count"] for item in manifest_datasets.values()),
    }
    evaluator_root = root / "official_evaluators"
    for source in EVALUATOR_SOURCES:
        evaluator_path = evaluator_root / source.dataset / f"{source.split}.py"
        _download(source, evaluator_path, retries=retries, refresh=refresh)
    manifest["official_evaluators"] = {
        "finqa": ["official_evaluators/finqa/evaluate.py"],
        "tatqa": [
            "official_evaluators/tatqa/tatqa_eval.py",
            "official_evaluators/tatqa/tatqa_metric.py",
            "official_evaluators/tatqa/tatqa_utils.py",
        ],
        "financebench": [],
    }
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    report_path = root / "report.md"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 公开金融 Benchmark 数据适配",
        "",
        "- 仅使用官方公开标签与官方划分；",
        "- Agent 输入和标准答案分目录保存，运行时不得向 Agent 注入 gold 文件；",
        "- 自有100家公司数据不参与这些准确率指标。",
        "",
        "| 数据集 | 案例数 | 官方任务 |",
        "|---|---:|---|",
    ]
    for name, item in manifest_datasets.items():
        lines.append(f"| {name} | {item['case_count']} | {item['evaluation_role']} |")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest_path, report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare official public financial benchmarks")
    parser.add_argument("--root", default="/artifacts/risk_data/public_benchmarks_v1")
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    paths = prepare_public_benchmarks(
        Path(args.root), retries=args.retries, refresh=args.refresh
    )
    print(json.dumps({"manifest": str(paths[0]), "report": str(paths[1])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
