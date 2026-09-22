from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


def build_program_skill(raw_train_path: Path, *, index_path: Path) -> dict[str, Any]:
    rows = json.loads(raw_train_path.read_text(encoding="utf-8"))
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(index_path) as connection:
        connection.execute("DROP TABLE IF EXISTS finqa_program_examples")
        connection.execute(
            """
            CREATE VIRTUAL TABLE finqa_program_examples USING fts5(
                case_id UNINDEXED,
                question,
                answer UNINDEXED,
                program UNINDEXED,
                tokenize='unicode61'
            )
            """
        )
        inserted = 0
        for row in rows:
            qa = row.get("qa") or {}
            question = str(qa.get("question") or "").strip()
            program = str(qa.get("program") or "").strip()
            if not question or not program:
                continue
            connection.execute(
                """
                INSERT INTO finqa_program_examples(case_id, question, answer, program)
                VALUES (?, ?, ?, ?)
                """,
                (str(row.get("id") or ""), question, str(qa.get("answer") or ""), program),
            )
            inserted += 1
        connection.execute(
            "INSERT INTO finqa_program_examples(finqa_program_examples) VALUES ('optimize')"
        )
    report = {
        "status": "READY",
        "source": "public FinQA train split",
        "evaluation_split_gold_included": False,
        "example_count": inserted,
        "index_path": str(index_path),
    }
    index_path.with_suffix(".report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


class FinQAProgramSkill:
    def __init__(self, index_path: Path) -> None:
        self.index_path = index_path

    @staticmethod
    def _query_expression(question: str) -> str:
        ignored = {
            "a", "an", "and", "are", "as", "at", "be", "by", "did", "do",
            "for", "from", "how", "in", "is", "it", "of", "on", "or", "the",
            "to", "was", "were", "what", "when", "which", "with", "would",
        }
        tokens = re.findall(r"[0-9A-Za-z][0-9A-Za-z._%-]*", question.lower())
        selected = [token for token in tokens if token not in ignored and len(token) > 1]
        if not selected:
            raise ValueError("FinQA question contains no searchable terms")
        return " OR ".join(f'"{token}"' for token in selected[:20])

    def search(
        self, *, question: str, case_id: str, top_k: int = 3
    ) -> list[dict[str, Any]]:
        expression = self._query_expression(question)
        with sqlite3.connect(self.index_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT case_id, question, answer, program,
                       bm25(finqa_program_examples) AS rank
                FROM finqa_program_examples
                WHERE finqa_program_examples MATCH ? AND case_id != ?
                ORDER BY rank
                LIMIT ?
                """,
                (expression, case_id, top_k),
            ).fetchall()
        return [
            {
                "case_id": str(row["case_id"]),
                "question": str(row["question"]),
                "answer": str(row["answer"]),
                "program": str(row["program"]),
                "source_split": "train",
                "score": -float(row["rank"]),
            }
            for row in rows
        ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the public FinQA program Skill")
    parser.add_argument(
        "--raw-train",
        default="/artifacts/risk_data/public_benchmarks_v1/raw/finqa/train.json",
    )
    parser.add_argument(
        "--index",
        default="/artifacts/agent_benchmarks/finqa_program_skill_v1/examples.sqlite",
    )
    args = parser.parse_args()
    report = build_program_skill(Path(args.raw_train), index_path=Path(args.index))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
