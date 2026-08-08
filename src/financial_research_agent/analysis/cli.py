from __future__ import annotations

import argparse
import json
from datetime import date

from financial_research_agent.analysis.batch import SparkFactorBatch
from financial_research_agent.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the versioned Spark factor batch")
    parser.add_argument("--universe", default="demo_liquid_a_share")
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args()
    result = SparkFactorBatch(Settings()).run(
        universe_id=args.universe,
        as_of_date=date.fromisoformat(args.as_of) if args.as_of else None,
    )
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
