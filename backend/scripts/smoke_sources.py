"""Live check: fetch every feed in FEEDS and report what came back.

Usage: `uv run python scripts/smoke_sources.py [--platform lemmy|reddit|imgflip]`
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from memepedia import contextdev
from memepedia.sources import FEEDS, Feed, SourceError, fetch


def _age(posted_at: datetime) -> str:
    seconds = (datetime.now(UTC) - posted_at).total_seconds()
    if seconds < 3600:
        return f"{seconds / 60:.0f}m ago"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h ago"
    return f"{seconds / 86400:.1f}d ago"


def _report_feed(feed: Feed) -> None:
    try:
        posts = fetch(feed)
    except SourceError as exc:
        print(f"{feed.key:35s} ERROR: {exc}")
        return
    if not posts:
        print(f"{feed.key:35s} 0 posts")
        return
    newest = max(posts, key=lambda p: p.posted_at)
    print(
        f"{feed.key:35s} n={len(posts):3d} newest={_age(newest.posted_at):>10s}  "
        f"sample={newest.title[:40]!r} {newest.image_url}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=["lemmy", "reddit", "imgflip"], default=None)
    args = parser.parse_args()

    for feed in FEEDS:
        if args.platform and feed.platform != args.platform:
            continue
        _report_feed(feed)

    print(f"\ncredits spent (lifetime, this ledger): {contextdev.credits_spent():.1f}")


if __name__ == "__main__":
    main()
