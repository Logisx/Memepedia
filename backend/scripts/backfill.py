"""One week of Lemmy history backfilled as sightings, so "this week in memes" has data.

FETCH, LOOK and RESOLVE exactly like a tick, across TopWeek-sorted Lemmy posts from the last
7 days spread evenly across feeds; no auto-trace, no clustering. Sightings are inserted with
seen_at=post.posted_at so old posts do not flood the wall as if they had just arrived. It looks
at no more images than the Gemini budget (memepedia/budget.py) still allows background work.

Usage: uv run python scripts/backfill.py [--max-images 120]
"""

from __future__ import annotations

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from memepedia import budget, db, store
from memepedia.config import get_settings
from memepedia.live import Thresholds, _archive_context, _look_one, classify
from memepedia.llm import RootInfo
from memepedia.models import Post, SightingState
from memepedia.resolver import Matcher
from memepedia.sources import FEEDS, Feed
from memepedia.sources.lemmy import fetch_lemmy

log = logging.getLogger("memepedia.live")

_PAGES = 3
_MAX_LIMIT = 200
_Outcome = SightingState | None


def _lemmy_feeds() -> list[Feed]:
    return [f for f in FEEDS if f.platform == "lemmy"]


def _recent_unknown(feed: Feed, cutoff: datetime) -> list[Post]:
    posts = fetch_lemmy(feed, sort="TopWeek", pages=_PAGES)
    known = store.known_post_urls([p.post_url for p in posts])
    return [p for p in posts if p.post_url not in known and p.posted_at >= cutoff]


def _gather(max_images: int) -> list[Post]:
    """This week's unknown posts, spread evenly across Lemmy feeds, capped at `max_images`."""
    feeds = _lemmy_feeds()
    per_feed = max(1, max_images // len(feeds))
    cutoff = datetime.now(UTC) - timedelta(days=7)
    batch: list[Post] = []
    for feed in feeds:
        batch.extend(_recent_unknown(feed, cutoff)[:per_feed])
    return batch[:max_images]


def _save_one(
    post: Post,
    roots: list[RootInfo],
    known_names: list[str],
    thresholds: Thresholds,
    matcher: Matcher,
) -> str:
    looked = _look_one(post, roots, known_names)
    if looked.error is not None:
        return "error"
    node_id, state = (
        (None, "unclassified")
        if looked.vision is None
        else classify(looked.vision, thresholds, matcher)
    )
    sid = store.insert_sighting(post, looked.vision, node_id, state, seen_at=post.posted_at)
    return state if sid is not None else "duplicate"


def _affordable(max_images: int) -> int:
    """How many images the Gemini budget lets the backfill look at; 0 when a guard says stop."""
    if (reason := budget.background_block()) is not None:
        print(f"backfill skipped: {reason}")
        return 0
    return min(max_images, int(budget.headroom("gemini")))


def backfill(max_images: int) -> dict[str, int]:
    """Backfills up to `max_images` Lemmy posts from the last 7 days; returns a state tally.

    Lemmy is read directly, so this spends no Context.dev credits; each image costs one Gemini
    call (plus one more for a near-match name), counted against the same caps as the live loop.
    """
    if max_images > _MAX_LIMIT:
        raise ValueError(f"--max-images may not exceed {_MAX_LIMIT}")
    affordable = _affordable(max_images)
    batch = _gather(affordable) if affordable > 0 else []
    roots, known_names = _archive_context()
    thresholds = Thresholds.from_settings(get_settings())
    matcher = Matcher.from_store()
    tally: dict[str, int] = {
        "resolved": 0,
        "pending": 0,
        "unclassified": 0,
        "error": 0,
        "duplicate": 0,
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(_save_one, post, roots, known_names, thresholds, matcher) for post in batch
        ]
        for future in futures:
            tally[future.result()] += 1
    return tally


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description="Backfill a week of Lemmy history.")
    parser.add_argument("--max-images", type=int, default=120)
    args = parser.parse_args()

    print(f"database: {db.describe_target()}")
    db.init_schema()
    tally = backfill(args.max_images)
    for key, count in tally.items():
        print(f"{key}: {count}")


if __name__ == "__main__":
    main()
