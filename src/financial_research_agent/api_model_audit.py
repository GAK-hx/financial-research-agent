from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx

from financial_research_agent.config import get_settings


MODEL_QUESTIONS = {
    "market": "分析贵州茅台最近一年的股价表现和趋势指标",
    "financial": "分析宁德时代最近三年的营收、利润和盈利能力",
    "report": "分析宁德时代最新研报中的技术创新观点",
    "comprehensive": "综合分析贵州茅台最近一年的股价表现、趋势指标和机构观点",
}


async def run() -> None:
    base_url = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
    selected_names = [
        name.strip()
        for name in os.environ.get("MODEL_AUDIT_CASES", "").split(",")
        if name.strip()
    ]
    cases = (
        {name: MODEL_QUESTIONS[name] for name in selected_names}
        if selected_names
        else MODEL_QUESTIONS
    )
    artifact_root = Path(get_settings().artifacts_root) / "model_runs"
    artifact_root.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict] = {}
    settings = get_settings()
    model_slug = (settings.model_name or "unconfigured").replace("/", "_")
    async with httpx.AsyncClient(base_url=base_url, timeout=300) as client:
        for name, question in cases.items():
            response = await client.post("/analyze", json={"question": question})
            body = response.json()
            artifact = {
                "name": name,
                "question": question,
                "http_status": response.status_code,
                "request_id": response.headers.get("x-request-id"),
                "response": body,
            }
            path = artifact_root / f"{model_slug}_{name}.json"
            path.write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            summary[name] = {
                "http_status": response.status_code,
                "run_id": body.get("run_id"),
                "success": body.get("success"),
                "planner_source": body.get("planner_source"),
                "reporting_status": body.get("reporting_status"),
                "validation_passed": (body.get("validation") or {}).get("passed"),
                "evidence_count": len(body.get("evidence") or []),
                "revision_used": body.get("timings", {}).get("revise_report") is not None,
                "api_total_ms": body.get("timings", {}).get("api_total"),
                "error": body.get("error"),
                "artifact": str(path),
            }
            if not (
                response.status_code == 200
                and body.get("success") is True
                and body.get("planner_source") == "model"
                and body.get("reporting_status") == "completed"
                and (body.get("validation") or {}).get("passed") is True
            ):
                print(json.dumps(summary, ensure_ascii=False, indent=2))
                raise RuntimeError(f"model API audit failed: {name}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(run())
