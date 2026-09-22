from __future__ import annotations

import json
from importlib.resources import files

from financial_research_agent.risk.models import IssuerPool


def load_correctness_pool() -> IssuerPool:
    path = files("financial_research_agent.risk").joinpath("correctness_pool_v1.json")
    return IssuerPool.model_validate(json.loads(path.read_text(encoding="utf-8")))
