from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from financial_research_agent.config import Settings
from financial_research_agent.persistence.database import (
    create_business_engine,
    create_session_factory,
)
from financial_research_agent.skills.models import SkillDefinition, SkillStatus
from financial_research_agent.skills.registry import SkillRegistry
from financial_research_agent.skills.store import SkillStore


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Review and publish versioned Skills")
    value.add_argument(
        "action",
        choices=["list", "import", "review", "activate", "deprecate", "bootstrap"],
    )
    value.add_argument("--version-id")
    value.add_argument("--file", type=Path)
    value.add_argument("--actor", default="local-operator")
    value.add_argument("--notes", default="")
    value.add_argument("--status", choices=[item.value for item in SkillStatus])
    return value


async def run(args: argparse.Namespace) -> None:
    settings = Settings()
    engine = create_business_engine(settings)
    store = SkillStore(create_session_factory(engine))
    try:
        if args.action == "list":
            status = SkillStatus(args.status) if args.status else None
            definitions = await store.definitions(status=status)
            print(
                json.dumps(
                    [item.model_dump(mode="json") for item in definitions],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        if args.action == "bootstrap":
            await store.bootstrap_builtins(
                SkillRegistry.from_builtin_catalog().versions(), actor=args.actor
            )
            print("built-in skills are present and audited")
            return
        if args.action == "import":
            if args.file is None:
                raise ValueError("--file is required for import")
            definition = SkillDefinition.model_validate_json(
                args.file.read_text(encoding="utf-8")
            )
            created = await store.import_draft(definition, actor=args.actor)
            print("created" if created else "already present")
            return
        if not args.version_id:
            raise ValueError("--version-id is required")
        if args.action == "review":
            result = await store.review(
                args.version_id, reviewer=args.actor, notes=args.notes
            )
        elif args.action == "activate":
            result = await store.activate(
                args.version_id, actor=args.actor, notes=args.notes
            )
        else:
            result = await store.deprecate(
                args.version_id, actor=args.actor, notes=args.notes
            )
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(run(parser().parse_args()))


if __name__ == "__main__":
    main()
