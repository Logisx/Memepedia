"""Live check: run one tick on one feed and print what it saved.

Usage: uv run python scripts/smoke_live.py --feed <key>
"""

from __future__ import annotations

import argparse

from memepedia import db
from memepedia.live import tick
from memepedia.sources import FEEDS


def _feed_keys() -> list[str]:
    return [feed.key for feed in FEEDS]


def _recent_sightings(feed_key: str, limit: int) -> list[db.Row]:
    return db.fetch_all(
        """
        SELECT s.title, s.state, s.node_id, n.name AS node_name, s.vision
        FROM sightings s LEFT JOIN nodes n ON n.id = s.node_id
        WHERE s.source = %s
        ORDER BY s.seen_at DESC
        LIMIT %s
        """,
        (feed_key, limit),
    )


def _print_sighting(row: db.Row) -> None:
    vision = row["vision"] or {}
    guess, confidence = vision.get("template_guess"), vision.get("confidence")
    node = row["node_name"] or row["node_id"] or "-"
    print(
        f"  [{row['state']:12s}] {row['title'][:40]!r:42s} "
        f"node={node!s:20s} guess={guess!r} confidence={confidence}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one live tick and print what it saved.")
    parser.add_argument("--feed", required=True, choices=_feed_keys())
    args = parser.parse_args()

    db.init_schema()
    report = tick(args.feed)
    print(report)
    print("\nsaved this tick:")
    for row in _recent_sightings(args.feed, max(report.looked, 1)):
        _print_sighting(row)


if __name__ == "__main__":
    main()
