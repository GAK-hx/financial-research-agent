from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


CANARY_EXCLUSIONS: dict[str, set[str]] = {
    "financebench": {
        "financebench_id_03029",
        "financebench_id_04672",
        "financebench_id_00499",
        "financebench_id_01226",
        "financebench_id_01865",
    },
    "finqa": {
        "V/2008/page_17.pdf-1",
        "C/2017/page_328.pdf-1",
        "DVN/2007/page_58.pdf-2",
        "ETR/2011/page_341.pdf-3",
        "ETR/2004/page_213.pdf-2",
    },
    "tatqa": {
        "23801627-ff77-4597-8d24-1c99e2452082",
        "4960801d-277d-4f79-8eca-c4d0200fa9d6",
        "593c4388-5209-4462-8b83-b429c8612c25",
        "f4142349-eb72-49eb-9a76-f3ccb1010cbc",
        "eb787966-fa02-401f-bfaf-ccabf3828b23",
    },
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _finqa_program_steps(program: str) -> int:
    return len(re.findall(r"(?:^|,\s+)[A-Za-z_]+\(", program))


def build_complex_subset(
    benchmark_root: Path,
    *,
    output_path: Path,
    per_benchmark: int = 20,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []

    finance_candidates = [
        row
        for row in _read_jsonl(
            benchmark_root / "gold" / "financebench" / "open_source.jsonl"
        )
        if len(row.get("evidence") or []) >= 2
        and str(row["case_id"]) not in CANARY_EXCLUSIONS["financebench"]
    ]
    for row in finance_candidates[:per_benchmark]:
        rows.append(
            {
                "benchmark": "financebench",
                "split": "open_source",
                "case_id": str(row["case_id"]),
                "selection_reason": "official_gold_requires_multiple_evidence_pages",
                "complexity": {"evidence_page_count": len(row.get("evidence") or [])},
                "gold_content_included": False,
            }
        )

    finqa_raw = json.loads(
        (benchmark_root / "raw" / "finqa" / "dev.json").read_text(encoding="utf-8")
    )
    finqa_candidates = []
    for row in finqa_raw:
        case_id = str(row["id"])
        steps = _finqa_program_steps(str((row.get("qa") or {}).get("program") or ""))
        if steps >= 2 and case_id not in CANARY_EXCLUSIONS["finqa"]:
            finqa_candidates.append((case_id, steps))
    for case_id, steps in finqa_candidates[:per_benchmark]:
        rows.append(
            {
                "benchmark": "finqa",
                "split": "dev",
                "case_id": case_id,
                "selection_reason": "official_program_has_multiple_operations",
                "complexity": {"program_steps": steps},
                "gold_content_included": False,
            }
        )

    tatqa_raw = json.loads(
        (benchmark_root / "raw" / "tatqa" / "dev.json").read_text(encoding="utf-8")
    )
    tatqa_by_type: dict[str, list[str]] = {"arithmetic": [], "multi-span": []}
    for document in tatqa_raw:
        for question in document.get("questions") or []:
            answer_type = str(question.get("answer_type") or "")
            case_id = str(question.get("uid") or question.get("id") or "")
            if (
                answer_type in tatqa_by_type
                and case_id
                and case_id not in CANARY_EXCLUSIONS["tatqa"]
            ):
                tatqa_by_type[answer_type].append(case_id)
    arithmetic_limit = per_benchmark // 2
    selected_tatqa = [
        *(('arithmetic', case_id) for case_id in tatqa_by_type["arithmetic"][:arithmetic_limit]),
        *(
            ('multi-span', case_id)
            for case_id in tatqa_by_type["multi-span"][: per_benchmark - arithmetic_limit]
        ),
    ]
    for answer_type, case_id in selected_tatqa:
        rows.append(
            {
                "benchmark": "tatqa",
                "split": "dev",
                "case_id": case_id,
                "selection_reason": "official_complex_answer_type",
                "complexity": {"answer_type": answer_type},
                "gold_content_included": False,
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    counts = {
        benchmark: sum(row["benchmark"] == benchmark for row in rows)
        for benchmark in ("financebench", "finqa", "tatqa")
    }
    report = {
        "status": "READY" if all(count == per_benchmark for count in counts.values()) else "PARTIAL",
        "source": "official public benchmark splits",
        "selection_uses_gold_metadata": True,
        "gold_content_included": False,
        "canary_cases_excluded": True,
        "per_benchmark_target": per_benchmark,
        "counts": counts,
        "manifest_path": str(output_path),
    }
    output_path.with_suffix(".report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze official complex benchmark subsets")
    parser.add_argument(
        "--benchmark-root",
        default="/artifacts/risk_data/public_benchmarks_v1",
    )
    parser.add_argument(
        "--output",
        default="/artifacts/agent_benchmarks/complex_subset_v1/manifest.jsonl",
    )
    parser.add_argument("--per-benchmark", type=int, default=20)
    args = parser.parse_args()
    print(
        json.dumps(
            build_complex_subset(
                Path(args.benchmark_root),
                output_path=Path(args.output),
                per_benchmark=args.per_benchmark,
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
