from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _clean_text(text: str) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def build_financebench_index(registry_path: Path, *, index_path: Path) -> dict[str, Any]:
    import pymupdf

    registry = _read_jsonl(registry_path)
    ready = [row for row in registry if row.get("status") == "READY"]
    if not ready:
        raise ValueError("FinanceBench registry contains no ready documents")

    index_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(index_path) as connection:
        connection.execute("DROP TABLE IF EXISTS financebench_pages")
        connection.execute(
            """
            CREATE VIRTUAL TABLE financebench_pages USING fts5(
                doc_name UNINDEXED,
                page_number UNINDEXED,
                text,
                tokenize='unicode61'
            )
            """
        )
        page_count = 0
        indexed_page_count = 0
        text_chars = 0
        for row in ready:
            path = Path(str(row["local_path"]))
            if not path.exists():
                raise FileNotFoundError(f"registered FinanceBench PDF not found: {path}")
            with pymupdf.open(path) as document:
                page_count += document.page_count
                for page_index, page in enumerate(document):
                    text = _clean_text(page.get_text("text"))
                    if not text:
                        continue
                    connection.execute(
                        "INSERT INTO financebench_pages(doc_name, page_number, text) VALUES (?, ?, ?)",
                        (row["doc_name"], page_index + 1, text),
                    )
                    indexed_page_count += 1
                    text_chars += len(text)
        connection.execute("INSERT INTO financebench_pages(financebench_pages) VALUES ('optimize')")

    report = {
        "status": "READY",
        "source": "official FinanceBench PDFs only",
        "gold_used_as_agent_input": False,
        "document_count": len(ready),
        "page_count": page_count,
        "indexed_page_count": indexed_page_count,
        "text_chars": text_chars,
        "index_path": str(index_path),
    }
    report_path = index_path.with_suffix(".report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


class FinanceBenchPageStore:
    def __init__(self, index_path: Path) -> None:
        self.index_path = index_path

    @staticmethod
    def _query_expression(query: str) -> str:
        tokens = re.findall(r"[0-9A-Za-z][0-9A-Za-z._%-]*", query.lower())
        ignored = {
            "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
            "how", "in", "is", "it", "of", "on", "or", "the", "to", "was",
            "were", "what", "when", "which", "with", "would",
        }
        selected = [token for token in tokens if token not in ignored and len(token) > 1]
        if not selected:
            raise ValueError("query contains no searchable terms")
        return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in selected)

    def search(self, *, doc_name: str, query: str, top_k: int = 8) -> list[dict[str, Any]]:
        expression = self._query_expression(query)
        with sqlite3.connect(self.index_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT doc_name, page_number, text, bm25(financebench_pages) AS rank
                FROM financebench_pages
                WHERE financebench_pages MATCH ? AND doc_name = ?
                ORDER BY rank
                LIMIT ?
                """,
                (expression, doc_name, top_k),
            ).fetchall()
        return [
            {
                "doc_name": str(row["doc_name"]),
                "page_number": int(row["page_number"]),
                "text": str(row["text"]),
                "score": -float(row["rank"]),
            }
            for row in rows
        ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build FinanceBench page search index")
    parser.add_argument(
        "--registry",
        default="/artifacts/agent_benchmarks/financebench_corpus_v1/document_registry.jsonl",
    )
    parser.add_argument(
        "--index",
        default="/artifacts/agent_benchmarks/financebench_index_v1/financebench_pages.sqlite",
    )
    args = parser.parse_args()
    report = build_financebench_index(Path(args.registry), index_path=Path(args.index))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
