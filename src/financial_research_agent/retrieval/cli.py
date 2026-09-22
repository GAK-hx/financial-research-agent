from __future__ import annotations

import argparse
import asyncio
import json

from financial_research_agent.config import get_settings
from financial_research_agent.retrieval.web import ElasticsearchWebDocumentIndex


async def initialize_index() -> None:
    settings = get_settings()
    if not settings.elasticsearch_enabled:
        raise RuntimeError("ELASTICSEARCH_ENABLED_REQUIRED")
    index = ElasticsearchWebDocumentIndex(settings)
    try:
        await index.initialize()
        print(
            json.dumps(
                {
                    "status": "ready",
                    "index": settings.elasticsearch_index_name,
                    "alias": settings.elasticsearch_index_alias,
                },
                ensure_ascii=False,
            )
        )
    finally:
        await index.client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Public web document index operations")
    parser.add_argument("command", choices=["init-index"])
    arguments = parser.parse_args()
    if arguments.command == "init-index":
        asyncio.run(initialize_index())


if __name__ == "__main__":
    main()
