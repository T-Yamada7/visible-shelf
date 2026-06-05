"""Orchestration entry point for VisibleShelf AI visibility diagnosis."""
import argparse
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

BASE = Path(__file__).parent


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AI visibility diagnosis for sake brands")
    p.add_argument("--target", default="config/targets.yaml")
    p.add_argument("--queries", default="config/queries.yaml")
    p.add_argument("--engines-cfg", default="config/engines.yaml")
    p.add_argument("--skip-api", action="store_true", help="Re-run extraction/scoring from existing raw/ files")
    p.add_argument("--engines", help="Comma-separated engine IDs to run (e.g. perplexity,chatgpt)")
    p.add_argument("--dry-run", action="store_true", help="Print query list without calling APIs")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    target_path = BASE / args.target
    queries_path = BASE / args.queries
    engines_path = BASE / args.engines_cfg
    raw_dir = BASE / "raw"
    out_dir = BASE / "out"

    engine_filter = [e.strip() for e in args.engines.split(",")] if args.engines else None

    if not args.skip_api:
        from src.runner import run
        results = run(
            target_path=target_path,
            queries_path=queries_path,
            engines_path=engines_path,
            raw_dir=raw_dir,
            out_dir=out_dir,
            engine_filter=engine_filter,
            dry_run=args.dry_run,
        )
        if args.dry_run:
            return
        print(f"\nAPI calls done. {len(results)} responses collected.")
    else:
        print("--skip-api: loading from raw/ (extractor/scorer not yet implemented)")


if __name__ == "__main__":
    main()
