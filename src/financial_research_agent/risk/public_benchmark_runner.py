from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from financial_research_agent.config import get_settings
from financial_research_agent.providers.model import build_model_provider
from financial_research_agent.risk.financebench_index import FinanceBenchPageStore
from financial_research_agent.risk.finqa_program_skill import FinQAProgramSkill


class RetrievalPlan(BaseModel):
    # Generation may propose extras; the Harness enforces the execution budget below.
    queries: list[str] = Field(min_length=1, max_length=8)


class RetrievalCoverageReview(BaseModel):
    status: Literal["COMPLETE", "SUPPLEMENT"]
    required_concepts: list[str] = Field(default_factory=list, max_length=8)
    supported_concepts: list[str] = Field(default_factory=list, max_length=8)
    missing_concepts: list[str] = Field(default_factory=list, max_length=4)
    supplemental_query: str = Field(default="", max_length=300)
    reason: str = Field(default="", max_length=800)


class PublicBenchmarkAnswer(BaseModel):
    answer: str | list[str]
    scale: str = ""
    program: str | None = None
    evidence_pages: list[int] = Field(default_factory=list, max_length=12)
    explanation: str = Field(default="", max_length=2000)


class ScalarBenchmarkAnswer(PublicBenchmarkAnswer):
    answer: str


class FinQABenchmarkAnswer(ScalarBenchmarkAnswer):
    # The team runtime replaces this with a locally executable quantitative-Agent
    # program when available. Empty synthesis output remains an official-score failure,
    # but should not turn an otherwise persisted case into an infrastructure failure.
    program: str = ""


class TatQABenchmarkAnswer(PublicBenchmarkAnswer):
    scale: Literal["", "thousand", "million", "billion", "percent"] = ""

    @field_validator("scale", mode="before")
    @classmethod
    def normalize_scale(cls, value: Any) -> str:
        normalized = str(value or "").strip().lower()
        return {
            "thousands": "thousand",
            "millions": "million",
            "billions": "billion",
            "%": "percent",
            "percentage": "percent",
        }.get(normalized, normalized)


def _answer_schema(benchmark: str) -> type[PublicBenchmarkAnswer]:
    if benchmark == "financebench":
        return ScalarBenchmarkAnswer
    if benchmark == "finqa":
        return FinQABenchmarkAnswer
    if benchmark == "tatqa":
        return TatQABenchmarkAnswer
    if benchmark == "risk_demo":
        return ScalarBenchmarkAnswer
    raise ValueError(f"unsupported benchmark: {benchmark}")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _financebench_document_text(path: Path) -> str:
    import pymupdf

    pages: list[str] = []
    with pymupdf.open(path) as document:
        for page_number, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            if text:
                pages.append(f"--- PAGE {page_number} ---\n{text}")
    return "\n\n".join(pages)


def _answer_instruction(benchmark: str, mode: str) -> str:
    common = (
        "Answer only from the supplied public benchmark context. Do not use outside facts. "
        "Return the shortest answer that directly resolves the question. Preserve units and "
        "scale. If the context is insufficient, say INSUFFICIENT_DATA rather than guessing. "
        "The explanation must be concise."
    )
    if benchmark == "financebench":
        return (
            f"{common} Put the final answer in answer and cite the supplied one-based PDF page "
            "numbers in evidence_pages. For numeric questions, include the requested currency "
            "and scale."
        )
    if benchmark == "finqa":
        return (
            f"{common} Also produce one FinQA program using official operators such as add, "
            "subtract, multiply, divide, exp, greater, table_average, table_sum or table_max. "
            "Use const_1, const_100 and similar official constants when appropriate. Put the "
            "executable program string in program."
        )
    if benchmark == "tatqa":
        return (
            f"{common} Set scale to one of the dataset scales such as thousand, million, billion, "
            "percent or an empty string. Lists are allowed for multi-span answers. For descriptive "
            "span questions, preserve the complete directly responsive source clause and its "
            "qualifications rather than shortening it to a paraphrase."
        )
    raise ValueError(f"unsupported benchmark: {benchmark}")


def _input_path(root: Path, benchmark: str, split: str) -> Path:
    return root / "inputs" / benchmark / f"{split}.jsonl"


def _load_registry(path: Path) -> dict[str, dict[str, Any]]:
    return {str(row["doc_name"]): row for row in _read_jsonl(path)}


def _filter_cases_by_manifest(
    cases: list[dict[str, Any]],
    *,
    manifest_path: Path | None,
    benchmark: str,
    split: str,
) -> list[dict[str, Any]]:
    if manifest_path is None:
        return cases
    manifest = [
        row
        for row in _read_jsonl(manifest_path)
        if str(row.get("benchmark")) == benchmark and str(row.get("split")) == split
    ]
    if not manifest:
        raise ValueError(f"manifest contains no cases for {benchmark}/{split}")
    if any(row.get("gold_content_included") is not False for row in manifest):
        raise ValueError("manifest must explicitly exclude Gold content")
    by_id = {str(case["case_id"]): case for case in cases}
    missing = [str(row["case_id"]) for row in manifest if str(row["case_id"]) not in by_id]
    if missing:
        raise ValueError(f"manifest case ids are missing from public inputs: {missing[:3]}")
    return [by_id[str(row["case_id"])] for row in manifest]


def _coverage_preview(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previews: list[dict[str, Any]] = []
    for page in pages:
        text = str(page.get("text") or "")
        if len(text) > 1800:
            text = f"{text[:900]}\n...[middle omitted]...\n{text[-900:]}"
        previews.append(
            {
                "page_number": page["page_number"],
                "text_preview": text,
            }
        )
    return previews


async def _prepare_case_payload(
    *,
    case: dict[str, Any],
    mode: Literal["direct", "single_agent"],
    provider: Any,
    page_store: FinanceBenchPageStore | None,
    document_registry: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    benchmark = str(case["benchmark"])
    if benchmark != "financebench":
        return (
            {"question": case["question"], "context": case.get("context", {})},
            [],
            [],
        )

    doc_names = [str(item) for item in case.get("document_refs", [])]
    if len(doc_names) != 1:
        raise ValueError(f"FinanceBench case requires exactly one document: {doc_names}")
    doc_name = doc_names[0]
    registry_item = document_registry.get(doc_name)
    if not registry_item or registry_item.get("status") != "READY":
        raise ValueError(f"FinanceBench document is unavailable: {doc_name}")

    if mode == "direct":
        document_text = _financebench_document_text(Path(str(registry_item["local_path"])))
        return (
            {
                "question": case["question"],
                "document": {"doc_name": doc_name, "text": document_text},
            },
            [],
            [],
        )

    if page_store is None:
        raise ValueError("single_agent FinanceBench mode requires a page store")
    plan_response = await provider.create_structured_response(
        instruction=(
            "Create one to three concise lexical search queries for the named SEC filing. "
            "Queries must target line items, accounting terms and periods present in the user's "
            "question. For a qualitative financial judgment, first translate the judgment into "
            "filing-based measures and cover every required numerator and denominator across the "
            "three queries. Prefer primary financial statements when they contain the needed "
            "values. Do not answer the question."
        ),
        input_payload={"question": case["question"], "doc_name": doc_name},
        schema=RetrievalPlan,
        max_tokens=256,
        operation="benchmark_retrieval_plan",
    )
    plan = RetrievalPlan.model_validate(plan_response.content)
    retrieved: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    executed_queries = plan.queries[:3]
    for query in executed_queries:
        for hit in page_store.search(doc_name=doc_name, query=query, top_k=6):
            key = (str(hit["doc_name"]), int(hit["page_number"]))
            if key in seen:
                continue
            seen.add(key)
            retrieved.append(hit)
    retrieved.sort(key=lambda item: float(item["score"]), reverse=True)
    initial_evidence = [
        {
            "doc_name": item["doc_name"],
            "page_number": item["page_number"],
            "text": item["text"],
        }
        for item in retrieved[:12]
    ]
    coverage_response = await provider.create_structured_response(
        instruction=(
            "Review whether the retrieved SEC filing pages contain every line item, period, "
            "unit and comparison needed to answer the question without outside knowledge. "
            "List the required concepts and the concepts directly supported by the page previews. "
            "A numeric concept is supported only when its period-matched value is visible, not "
            "when the term is merely mentioned. "
            "Do not answer the question and do not use benchmark Gold. Return COMPLETE when "
            "the evidence is sufficient. Otherwise return SUPPLEMENT and exactly one concise "
            "lexical query targeting only the missing concepts. A qualitative judgment may "
            "require its numerator, denominator and comparison basis. Do not request an "
            "external industry benchmark when the filing's own figures can resolve the task."
        ),
        input_payload={
            "question": case["question"],
            "doc_name": doc_name,
            "executed_queries": executed_queries,
            "retrieved_page_previews": _coverage_preview(initial_evidence),
        },
        schema=RetrievalCoverageReview,
        max_tokens=400,
        operation="benchmark_retrieval_coverage",
    )
    coverage = RetrievalCoverageReview.model_validate(coverage_response.content)
    supplemental_query = coverage.supplemental_query.strip()
    supplement_required = (
        coverage.status == "SUPPLEMENT" or bool(coverage.missing_concepts)
    )
    if supplement_required and not supplemental_query:
        supplemental_query = " ".join(coverage.missing_concepts[:2]).strip()
    supplemental_pages: list[dict[str, Any]] = []
    if (
        supplement_required
        and supplemental_query
        and supplemental_query.lower() not in {query.lower() for query in executed_queries}
    ):
        executed_queries.append(supplemental_query)
        for hit in page_store.search(
            doc_name=doc_name,
            query=supplemental_query,
            top_k=6,
        ):
            key = (str(hit["doc_name"]), int(hit["page_number"]))
            if key in seen:
                continue
            seen.add(key)
            supplemental_pages.append(hit)
        # Give the targeted follow-up up to four slots while retaining the strongest
        # initial results. The final context remains capped at twelve pages.
        supplemental_pages = supplemental_pages[:4]
    combined = [*supplemental_pages, *retrieved]
    final_pages: list[dict[str, Any]] = []
    final_seen: set[tuple[str, int]] = set()
    for item in combined:
        key = (str(item["doc_name"]), int(item["page_number"]))
        if key in final_seen:
            continue
        final_seen.add(key)
        final_pages.append(item)
        if len(final_pages) >= 12:
            break
    evidence = [
        {
            "doc_name": item["doc_name"],
            "page_number": item["page_number"],
            "text": item["text"],
        }
        for item in final_pages
    ]
    return (
        {
            "question": case["question"],
            "document": doc_name,
            "retrieved_pages": evidence,
            "retrieval_coverage": {
                **coverage.model_dump(mode="json"),
                "effective_status": (
                    "SUPPLEMENT" if supplement_required else "COMPLETE"
                ),
                "executed_supplemental_query": (
                    supplemental_query if supplemental_pages else ""
                ),
                "supplement_executed": bool(supplemental_pages),
                "supplemental_pages": [
                    int(item["page_number"]) for item in supplemental_pages
                ],
            },
        },
        executed_queries,
        [
            plan_response.usage.model_dump(mode="json"),
            coverage_response.usage.model_dump(mode="json"),
        ],
    )


async def run_public_benchmark(
    *,
    benchmark_root: Path,
    corpus_registry_path: Path,
    index_path: Path,
    output_root: Path,
    benchmark: Literal["financebench", "finqa", "tatqa"],
    split: str,
    mode: Literal["direct", "single_agent"],
    limit: int | None,
    case_id: str | None,
    resume: bool,
    retry_failures: bool,
    finqa_skill_index_path: Path,
    case_manifest_path: Path | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    provider = build_model_provider(settings)
    input_path = _input_path(benchmark_root, benchmark, split)
    cases = _read_jsonl(input_path)
    cases = _filter_cases_by_manifest(
        cases,
        manifest_path=case_manifest_path,
        benchmark=benchmark,
        split=split,
    )
    if case_id:
        cases = [item for item in cases if str(item["case_id"]) == case_id]
    if limit is not None:
        cases = cases[:limit]
    if not cases:
        raise ValueError("no benchmark cases selected")

    document_registry = (
        _load_registry(corpus_registry_path) if benchmark == "financebench" else {}
    )
    page_store = (
        FinanceBenchPageStore(index_path)
        if benchmark == "financebench" and mode == "single_agent"
        else None
    )
    program_skill = (
        FinQAProgramSkill(finqa_skill_index_path)
        if benchmark == "finqa" and finqa_skill_index_path.exists()
        else None
    )
    output_root.mkdir(parents=True, exist_ok=True)
    results_path = output_root / "results.jsonl"
    failures_path = output_root / "failures.jsonl"
    results = _read_jsonl(results_path) if resume and results_path.exists() else []
    failures = _read_jsonl(failures_path) if resume and failures_path.exists() else []
    previous_failure_count = 0
    if resume and retry_failures and failures:
        previous_failure_count = len(failures)
        previous_failures_path = output_root / "failures.previous.jsonl"
        previous_failures_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in failures),
            encoding="utf-8",
        )
        failures = []
        failures_path.write_text("", encoding="utf-8")
    if not resume:
        results_path.write_text("", encoding="utf-8")
        failures_path.write_text("", encoding="utf-8")
    completed_ids = {str(item["case_id"]) for item in [*results, *failures]}
    try:
        for case in cases:
            if str(case["case_id"]) in completed_ids:
                continue
            started = time.perf_counter()
            stage = "prepare_payload"
            try:
                payload, queries, planning_usage = await _prepare_case_payload(
                    case=case,
                    mode=mode,
                    provider=provider,
                    page_store=page_store,
                    document_registry=document_registry,
                )
                program_examples: list[dict[str, Any]] = []
                if program_skill is not None:
                    program_examples = program_skill.search(
                        question=str(case["question"]),
                        case_id=str(case["case_id"]),
                        top_k=3,
                    )
                    payload = {
                        **payload,
                        "finqa_program_skill": {
                            "source_split": "train",
                            "examples": program_examples,
                            "usage_policy": (
                                "Syntax and operation-pattern guidance only; examples are not "
                                "evidence for the current answer."
                            ),
                        },
                    }
                stage = "answer"
                answer_schema = _answer_schema(benchmark)
                response = await provider.create_structured_response(
                    instruction=_answer_instruction(benchmark, mode),
                    input_payload=payload,
                    schema=answer_schema,
                    max_tokens=2048,
                    operation=f"benchmark_{benchmark}_{mode}_answer",
                )
                answer = answer_schema.model_validate(response.content)
                result = {
                        "benchmark": benchmark,
                        "split": split,
                        "case_id": case["case_id"],
                        "mode": mode,
                        "model": settings.model_name,
                        "prediction": answer.model_dump(mode="json"),
                        "search_queries": queries,
                        "retrieval_coverage": payload.get("retrieval_coverage", {}),
                        "public_train_skill_used": bool(program_examples),
                        "usage": [*planning_usage, response.usage.model_dump(mode="json")],
                        "latency_seconds": round(time.perf_counter() - started, 3),
                    }
                results.append(result)
                with results_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(result, ensure_ascii=False) + "\n")
            except Exception as exc:  # noqa: BLE001 - persist benchmark failures for review
                failure = {
                        "benchmark": benchmark,
                        "split": split,
                        "case_id": case.get("case_id"),
                        "mode": mode,
                        "model": settings.model_name,
                        "stage": stage,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "raw_output": str(getattr(exc, "raw_output", "")),
                        "latency_seconds": round(time.perf_counter() - started, 3),
                    }
                failures.append(failure)
                with failures_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(failure, ensure_ascii=False) + "\n")
    finally:
        await provider.aclose()

    report = {
        "status": "PASS" if results and not failures else "PARTIAL" if results else "FAIL",
        "benchmark": benchmark,
        "split": split,
        "mode": mode,
        "model": settings.model_name,
        "selected_cases": len(cases),
        "successful_cases": len(results),
        "failed_cases": len(failures),
        "retried_previous_failures": previous_failure_count,
        "gold_used_during_inference": False,
        "evaluation_split_gold_used_during_inference": False,
        "public_train_skill_used": program_skill is not None,
        "results_path": str(results_path),
        "failures_path": str(failures_path),
    }
    failure_markdown_path = output_root / "failures.md"
    failure_lines = [
        "# 公开 Benchmark 失败记录",
        "",
        f"- 数据集：`{benchmark}` / `{split}`",
        f"- 模式：`{mode}`",
        f"- 模型：`{settings.model_name}`",
        f"- 失败数：{len(failures)}",
        "",
    ]
    if not failures:
        failure_lines.append("本轮无失败案例。")
    for failure in failures:
        failure_lines.extend(
            [
                f"## {failure['case_id']}",
                "",
                f"- 错误：`{failure['error_type']}` — {failure['error']}",
                f"- 阶段：`{failure.get('stage', 'unknown')}`",
                f"- 耗时：{failure['latency_seconds']} 秒",
                "- 模型原始输出：",
                "",
                "```text",
                str(failure.get("raw_output") or "未捕获；该记录生成于原始输出持久化启用前。")
                .replace("```", "'''"),
                "```",
                "",
            ]
        )
    failure_markdown_path.write_text("\n".join(failure_lines) + "\n", encoding="utf-8")
    report["failures_markdown_path"] = str(failure_markdown_path)
    (output_root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run public financial benchmark inference")
    parser.add_argument(
        "--benchmark-root",
        default="/artifacts/phase5_step01/public_benchmarks_v1",
    )
    parser.add_argument(
        "--corpus-registry",
        default="/artifacts/phase5_step02/financebench_corpus_v1/document_registry.jsonl",
    )
    parser.add_argument(
        "--index",
        default="/artifacts/phase5_step02/financebench_index_v1/financebench_pages.sqlite",
    )
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--benchmark", choices=("financebench", "finqa", "tatqa"), required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--mode", choices=("direct", "single_agent"), required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--case-id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--retry-failures",
        action="store_true",
        help="With --resume, preserve then selectively rerun only failed cases.",
    )
    parser.add_argument(
        "--finqa-skill-index",
        default="/artifacts/phase5_step02/finqa_program_skill_v1/examples.sqlite",
    )
    parser.add_argument("--case-manifest")
    args = parser.parse_args()
    report = asyncio.run(
        run_public_benchmark(
            benchmark_root=Path(args.benchmark_root),
            corpus_registry_path=Path(args.corpus_registry),
            index_path=Path(args.index),
            output_root=Path(args.output_root),
            benchmark=args.benchmark,
            split=args.split,
            mode=args.mode,
            limit=args.limit,
            case_id=args.case_id,
            resume=args.resume,
            retry_failures=args.retry_failures,
            finqa_skill_index_path=Path(args.finqa_skill_index),
            case_manifest_path=(Path(args.case_manifest) if args.case_manifest else None),
        )
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
