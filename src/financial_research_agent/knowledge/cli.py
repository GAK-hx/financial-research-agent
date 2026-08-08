from __future__ import annotations

import argparse
import asyncio

from financial_research_agent.config import get_settings
from financial_research_agent.knowledge.lake import KnowledgeLake
from financial_research_agent.knowledge.pipeline import KnowledgePipeline
from financial_research_agent.knowledge.source import LocalJsonKnowledgeSource
from financial_research_agent.knowledge.store import KnowledgeStore
from financial_research_agent.persistence.database import (
    create_business_engine,
    create_session_factory,
)


async def run(limit: int) -> None:
    settings = get_settings()
    engine = create_business_engine(settings)
    try:
        source = LocalJsonKnowledgeSource(settings.knowledge_source_path or None)
        pipeline = KnowledgePipeline(
            source=source,
            lake=KnowledgeLake(settings),
            store=KnowledgeStore(create_session_factory(engine)),
            allowed_symbols=set(settings.stock_codes),
        )
        result = await pipeline.run_once(limit=limit)
        print(result.model_dump_json(indent=2))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest governed external event knowledge")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    asyncio.run(run(args.limit))


if __name__ == "__main__":
    main()
