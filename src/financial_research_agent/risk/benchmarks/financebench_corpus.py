from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


METADATA_URL = (
    "https://raw.githubusercontent.com/patronus-ai/financebench/main/"
    "data/financebench_document_information.jsonl"
)
PDF_BASE_URL = (
    "https://raw.githubusercontent.com/patronus-ai/financebench/main/pdfs"
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _download(url: str, path: Path, *, retries: int, require_pdf: bool = False) -> int:
    if path.exists() and path.stat().st_size > 0:
        if not require_pdf or path.read_bytes()[:5] == b"%PDF-":
            return path.stat().st_size
    path.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for attempt in range(1, retries + 1):
        try:
            request = Request(url, headers={"User-Agent": "financial-agent-benchmark/1.0"})
            with urlopen(request, timeout=180) as response:  # noqa: S310 - official fixed source
                payload = response.read()
            if not payload:
                raise ValueError("empty response")
            if require_pdf and not payload.startswith(b"%PDF-"):
                raise ValueError("response is not a PDF")
            path.write_bytes(payload)
            return len(payload)
        except Exception as exc:  # noqa: BLE001 - preserve network failure details
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
            if attempt < retries:
                time.sleep(min(60, 2**attempt))
    raise RuntimeError(f"failed to download {url}: {'; '.join(errors)}")


def prepare_financebench_corpus(
    benchmark_root: Path,
    *,
    output_root: Path,
    retries: int = 6,
    limit: int | None = None,
    metadata_only: bool = False,
) -> tuple[Path, Path]:
    input_path = benchmark_root / "inputs" / "financebench" / "open_source.jsonl"
    if not input_path.exists():
        raise FileNotFoundError(f"FinanceBench inputs not found: {input_path}")

    metadata_path = benchmark_root / "raw" / "financebench" / "document_information.jsonl"
    _download(METADATA_URL, metadata_path, retries=retries)
    metadata = {str(row["doc_name"]): row for row in _read_jsonl(metadata_path)}

    referenced = sorted(
        {
            str(document_ref)
            for row in _read_jsonl(input_path)
            for document_ref in row.get("document_refs", [])
        }
    )
    missing = [doc_name for doc_name in referenced if doc_name not in metadata]
    if missing:
        raise ValueError(f"official metadata is missing referenced documents: {missing}")

    selected = referenced[:limit] if limit is not None else referenced
    document_root = output_root / "documents"
    registry_rows: list[dict[str, Any]] = []
    total_bytes = 0
    for doc_name in selected:
        item = metadata[doc_name]
        local_path = document_root / f"{doc_name}.pdf"
        official_repository_url = f"{PDF_BASE_URL}/{doc_name}.pdf"
        size_bytes = 0
        status = "METADATA_ONLY"
        if not metadata_only:
            size_bytes = _download(
                official_repository_url,
                local_path,
                retries=retries,
                require_pdf=True,
            )
            total_bytes += size_bytes
            status = "READY"
        registry_rows.append(
            {
                "doc_name": doc_name,
                "company": item.get("company"),
                "gics_sector": item.get("gics_sector"),
                "doc_type": item.get("doc_type"),
                "doc_period": item.get("doc_period"),
                "publisher_url": item.get("doc_link"),
                "official_repository_url": official_repository_url,
                "local_path": str(local_path) if not metadata_only else None,
                "size_bytes": size_bytes,
                "status": status,
            }
        )

    output_root.mkdir(parents=True, exist_ok=True)
    registry_path = output_root / "document_registry.jsonl"
    registry_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in registry_rows),
        encoding="utf-8",
    )
    report = {
        "status": "READY" if len(selected) == len(referenced) and not metadata_only else "PARTIAL",
        "source": "official patronus-ai/financebench repository",
        "gold_used_as_agent_input": False,
        "referenced_document_count": len(referenced),
        "prepared_document_count": len(selected),
        "metadata_only": metadata_only,
        "total_bytes": total_bytes,
        "registry_path": str(registry_path),
    }
    report_path = output_root / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path = output_root / "report.md"
    markdown_path.write_text(
        "\n".join(
            [
                "# FinanceBench 官方文档语料",
                "",
                f"- 状态：`{report['status']}`",
                f"- 问题引用文档：{len(referenced)}",
                f"- 本次准备文档：{len(selected)}",
                f"- 下载大小：{total_bytes / 1024 / 1024:.2f} MiB",
                "- 来源：Patronus AI 官方 FinanceBench 仓库；",
                "- Agent 输入未使用 Gold 答案、Gold Evidence 或人工 justification。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return registry_path, report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare official FinanceBench source PDFs")
    parser.add_argument(
        "--benchmark-root",
        default="/artifacts/risk_data/public_benchmarks_v1",
    )
    parser.add_argument(
        "--output-root",
        default="/artifacts/agent_benchmarks/financebench_corpus_v1",
    )
    parser.add_argument("--retries", type=int, default=6)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--metadata-only", action="store_true")
    args = parser.parse_args()
    registry, report = prepare_financebench_corpus(
        Path(args.benchmark_root),
        output_root=Path(args.output_root),
        retries=args.retries,
        limit=args.limit,
        metadata_only=args.metadata_only,
    )
    print(json.dumps({"registry": str(registry), "report": str(report)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
