from __future__ import annotations

import json
import math
import time
from importlib.resources import files
from pathlib import Path

from financial_research_agent.config import get_settings
from financial_research_agent.rag.embedding import BgeEmbeddingModel
from financial_research_agent.rag.store import HybridReportStore


def _score(cases: list[dict], results: dict[str, list]) -> dict:
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    for case in cases:
        hits = results[case["case_id"]]
        ranks = [
            index
            for index, hit in enumerate(hits, start=1)
            if case["expected_title_contains"] in hit.report_title
        ]
        rank = ranks[0] if ranks else None
        recalls.append(1.0 if rank else 0.0)
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
        ndcgs.append(1.0 / math.log2(rank + 1) if rank else 0.0)
    count = max(1, len(cases))
    return {
        "recall_at_k": sum(recalls) / count,
        "mrr_at_k": sum(reciprocal_ranks) / count,
        "ndcg_at_k": sum(ndcgs) / count,
    }


def evaluate(top_k: int = 5) -> dict:
    settings = get_settings()
    cases = json.loads(
        files("financial_research_agent.rag")
        .joinpath("evaluation_cases.json")
        .read_text(encoding="utf-8")
    )
    embedder = BgeEmbeddingModel(settings.rag_embedding_model)
    store = HybridReportStore(settings)
    store.prepare(embedder.dimension, mode="skip")
    dense_results = {}
    hybrid_results = {}
    dense_latency: list[float] = []
    hybrid_latency: list[float] = []
    for case in cases:
        vector = embedder.encode([case["query"]])[0]
        started = time.perf_counter()
        dense_results[case["case_id"]] = store.dense.search(
            vector, case["stock_code"], top_k
        )
        dense_latency.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        hybrid_results[case["case_id"]] = store.search(
            vector,
            case["stock_code"],
            top_k,
            query_text=case["query"],
        )
        hybrid_latency.append((time.perf_counter() - started) * 1000)
    dense_score = _score(cases, dense_results)
    hybrid_score = _score(cases, hybrid_results)
    report = {
        "top_k": top_k,
        "case_count": len(cases),
        "dense": {
            **dense_score,
            "mean_latency_ms": sum(dense_latency) / len(dense_latency),
        },
        "hybrid": {
            **hybrid_score,
            "mean_latency_ms": sum(hybrid_latency) / len(hybrid_latency),
        },
        "gate": {
            "hybrid_recall_not_below_dense": (
                hybrid_score["recall_at_k"] >= dense_score["recall_at_k"]
            ),
            "hybrid_ndcg_not_below_dense": (
                hybrid_score["ndcg_at_k"] >= dense_score["ndcg_at_k"]
            ),
        },
        "cases": [
            {
                **case,
                "dense_hits": [item.chunk_id for item in dense_results[case["case_id"]]],
                "hybrid_hits": [item.chunk_id for item in hybrid_results[case["case_id"]]],
            }
            for case in cases
        ],
    }
    output = Path(settings.artifacts_root) / "phase4" / "step02" / "rag_evaluation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
