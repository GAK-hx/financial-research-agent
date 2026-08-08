from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from financial_research_agent.rag.embedding import BgeEmbeddingModel
from financial_research_agent.rag.parser import parse_directory
from financial_research_agent.rag.store import MilvusReportStore

FIXED_QUERIES = (
    ("600519", "i茅台渠道改革效果"),
    ("300750", "神行超充电池与补能生态"),
)


def run_audit(host: str, port: int, reports_dir: str, rebuild: bool) -> dict:
    settings = SimpleNamespace(milvus_host=host, milvus_port=port)
    documents, chunks = parse_directory(Path(reports_dir))
    embedder = BgeEmbeddingModel()
    vectors = embedder.encode([chunk.text for chunk in chunks])
    store = MilvusReportStore(settings)
    store.prepare(embedder.dimension, mode="rebuild" if rebuild else "skip")
    before = store.count()
    inserted = store.insert(chunks, vectors) if rebuild or before == 0 else 0
    query_results = []
    cross_stock_errors = 0
    for stock_code, query in FIXED_QUERIES:
        query_vector = embedder.encode([query])[0]
        hits = store.search(query_vector, stock_code, 5)
        cross_stock_errors += sum(hit.stock_code != stock_code for hit in hits)
        query_results.append(
            {
                "stock_code": stock_code,
                "query": query,
                "hits": [
                    {
                        "institution": hit.institution,
                        "title": hit.report_title,
                        "page": hit.page_number,
                        "score": round(hit.score, 6),
                        "chunk_id": hit.chunk_id,
                        "text_preview": hit.text[:120],
                    }
                    for hit in hits
                ],
            }
        )
    return {
        "documents": len(documents),
        "pages": sum(document.page_count for document in documents),
        "chunks": len(chunks),
        "metadata_complete": sum(
            bool(chunk.stock_code and chunk.institution and chunk.report_title and chunk.page_number)
            for chunk in chunks
        ),
        "dimension": embedder.dimension,
        "entities_before": before,
        "inserted": inserted,
        "entities_after": store.count(),
        "cross_stock_errors": cross_stock_errors,
        "queries": query_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit the research report index")
    parser.add_argument("--host", default="milvus")
    parser.add_argument("--port", type=int, default=19530)
    parser.add_argument("--reports-dir", default="/data/reports")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run_audit(args.host, args.port, args.reports_dir, args.rebuild),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
