"""Live smoke test for memepedia.trace: prints each event as it arrives, then credits spent.

Usage: uv run python scripts/smoke_trace.py --query "Doomer" [--context "..."] [--specimen]
"""

from __future__ import annotations

import argparse
import logging
import time

from memepedia import contextdev, db, trace


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Trace one meme live and print its events.")
    parser.add_argument("--query", type=str, required=True)
    parser.add_argument("--context", type=str, default=None)
    parser.add_argument("--specimen", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    db.init_schema()
    before = contextdev.credits_spent()
    start = time.monotonic()
    for event in trace.trace(args.query, context=args.context, as_specimen=args.specimen):
        elapsed = time.monotonic() - start
        print(f"[{elapsed:6.2f}s] {event.model_dump_json()}")
    spent = contextdev.credits_spent() - before
    print(f"credits spent: {spent:.1f}")


if __name__ == "__main__":
    main()
