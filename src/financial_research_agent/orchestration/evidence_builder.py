from __future__ import annotations

from financial_research_agent.domain.models import Evidence, ToolResult


class EvidenceBuilder:
    def build(
        self, run_id: str, tool_results: list[ToolResult], max_evidence: int
    ) -> list[Evidence]:
        candidates = [
            item for result in tool_results if result.success for item in result.evidence
        ]
        if len(candidates) > max_evidence:
            raise ValueError("run exceeds evidence budget")
        original_ids = [item.evidence_id for item in candidates]
        if len(original_ids) != len(set(original_ids)):
            raise ValueError("duplicate evidence id in one run")
        built: list[Evidence] = []
        for item in candidates:
            self._validate_source(item)
            source = item.source.model_copy(
                update={
                    "metadata": {
                        **item.source.metadata,
                        "original_evidence_id": item.evidence_id,
                    }
                }
            )
            built.append(
                item.model_copy(
                    update={
                        "evidence_id": f"{run_id}:{item.evidence_id}",
                        "source": source,
                    }
                )
            )
        return built

    @staticmethod
    def _validate_source(item: Evidence) -> None:
        expected_source = {
            "market": "iceberg",
            "financial": "iceberg",
            "indicator": "calculation",
            "research_report": "milvus",
            "technical": "calculation",
            "fundamental": "calculation",
            "factor": "iceberg",
            "event": "knowledge",
            "comparison": "calculation",
        }[item.evidence_type]
        if item.source.source_type != expected_source or not item.source.locator:
            raise ValueError(f"invalid source chain for {item.evidence_type}")
        if item.evidence_type in {"indicator", "technical", "fundamental", "comparison"}:
            if not item.source.metadata.get("formula_version"):
                raise ValueError(f"{item.evidence_type} evidence requires formula_version")
            if not item.source.metadata.get("input_locator"):
                raise ValueError(f"{item.evidence_type} evidence requires input_locator")
        if item.evidence_type == "research_report":
            required = ("institution", "report_title", "page_number", "chunk_id")
            if any(not item.data.get(field) for field in required):
                raise ValueError("research report evidence lacks attribution or page chain")
        if item.evidence_type == "factor":
            required = ("registry_version", "universe_version", "run_id")
            if any(not item.source.metadata.get(field) for field in required):
                raise ValueError("factor evidence lacks registry, universe or run lineage")
        if item.evidence_type == "event":
            required = ("event_id", "source_url", "available_at", "status")
            if any(not item.source.metadata.get(field) for field in required):
                raise ValueError("event evidence lacks activation or source lineage")
