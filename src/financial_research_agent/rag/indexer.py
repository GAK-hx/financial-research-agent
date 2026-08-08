from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from financial_research_agent.config import get_settings
from financial_research_agent.rag.embedding import BgeEmbeddingModel
from financial_research_agent.rag.parser import parse_directory
from financial_research_agent.rag.store import COLLECTION_NAME, HybridReportStore


def build_index(mode: str) -> dict:
    settings = get_settings()
    documents, chunks = parse_directory(Path(settings.reports_dir))
    output_dir = Path(settings.lake_root) / "metadata" / "rag_indexes"
    output_dir.mkdir(parents=True, exist_ok=True)
    stats_path = output_dir / f"{COLLECTION_NAME}.json"
    previous_versions: dict[str, str] = {}
    if mode == "incremental" and stats_path.exists():
        try:
            previous = json.loads(stats_path.read_text(encoding="utf-8"))
            previous_versions = {
                str(key): str(value)
                for key, value in previous.get("document_versions", {}).items()
            }
        except (OSError, ValueError, TypeError):
            previous_versions = {}
    embedder = BgeEmbeddingModel(settings.rag_embedding_model)
    store = HybridReportStore(settings)
    store.prepare(embedder.dimension, mode=mode)
    before = store.dense.count()
    inserted = 0
    pruned_documents = 0
    current_versions = {
        item.document_id: item.document_version for item in documents
    }
    changed_document_ids: set[str] = set()
    if mode == "rebuild" or before == 0:
        changed_document_ids = set(current_versions)
    elif mode == "incremental":
        changed_document_ids = {
            document_id
            for document_id, version in current_versions.items()
            if previous_versions.get(document_id) != version
        }
    if mode in {"rebuild", "incremental"} or before == 0:
        pruned_documents = store.prune_documents(
            set(current_versions)
        )
        changed_chunks = [
            item for item in chunks if item.document_id in changed_document_ids
        ]
        if changed_chunks:
            vectors = embedder.encode([chunk.text for chunk in changed_chunks])
            inserted = store.replace(changed_chunks, vectors)
    dense_after, keyword_after = store.assert_consistent()
    stats = {
        "collection": COLLECTION_NAME,
        "mode": mode,
        "documents": len(documents),
        "chunks": len(chunks),
        "embedding_model": embedder.model_name,
        "embedding_dimension": embedder.dimension,
        "entities_before": before,
        "inserted": inserted,
        "changed_documents": len(changed_document_ids),
        "unchanged_documents": len(documents) - len(changed_document_ids),
        "pruned_documents": pruned_documents,
        "entities_after": dense_after,
        "keyword_entities_after": keyword_after,
        "keyword_index": settings.rag_keyword_index_path,
        "document_versions": current_versions,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
    }
    stats_path.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the research report vector index")
    parser.add_argument(
        "--mode", choices=("skip", "incremental", "rebuild"), default="incremental"
    )
    args = parser.parse_args()
    print(json.dumps(build_index(args.mode), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
