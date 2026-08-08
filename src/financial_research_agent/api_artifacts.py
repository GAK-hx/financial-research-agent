from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx

from financial_research_agent.config import get_settings
from financial_research_agent.data_management.storage import JsonArtifactStore

DEMO_QUESTIONS = {
    "market": "分析贵州茅台最近一年的股价表现",
    "report": "分析宁德时代最新研报中的技术创新观点",
    "comprehensive": "分析贵州茅台最近一年的股价表现和研报观点",
}


async def run() -> None:
    base_url = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
    store = JsonArtifactStore(get_settings().lake_root, "demo_runs")
    mirror_root = Path(get_settings().artifacts_root) / "demo_runs"
    mirror_root.mkdir(parents=True, exist_ok=True)
    saved = []
    async with httpx.AsyncClient(base_url=base_url, timeout=90) as client:
        for name, question in DEMO_QUESTIONS.items():
            response = await client.post("/analyze", json={"question": question})
            artifact = {
                "name": name,
                "question": question,
                "http_status": response.status_code,
                "request_id": response.headers.get("x-request-id"),
                "response": response.json(),
            }
            path = store.save(f"api_{name}", artifact)
            (mirror_root / f"api_{name}.json").write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            saved.append(str(path))
    print(json.dumps({"saved": saved}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(run())
