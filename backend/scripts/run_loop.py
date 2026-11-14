"""The laptop clock: visits feeds in rotation so sightings arrive as a steady trickle.

Used until the backend has a public URL for Context.dev webhooks. After each full rotation,
runs detect_specimens() and store.expire_specimens().

Usage: uv run python scripts/run_loop.py [--every 45] [--once] [--platform lemmy|reddit|imgflip]
"""

from __future__ import annotations

import argparse
import logging
import signal
import time
from types import FrameType

from memepedia import db, store
from memepedia.live import TickReport, detect_specimens, tick
from memepedia.models import Platform
from memepedia.sources import FEEDS, Feed

log = logging.getLogger("memepedia.live")

_stop_requested = False


def _request_stop(signum: int, frame: FrameType | None) -> None:
    global _stop_requested
    _stop_requested = True


def _feeds_for(platform: Platform | None) -> list[Feed]:
    return [f for f in FEEDS if platform is None or f.platform == platform]


def _log_report(report: TickReport) -> None:
    log.info(
        "tick %-35s fetched=%-3d fresh=%-3d looked=%-3d resolved=%-3d pending=%-3d "
        "unclassified=%-3d traced=%-2d errors=%s",
        report.feed,
        report.fetched,
        report.fresh,
        report.looked,
        report.resolved,
        report.pending,
        report.unclassified,
        len(report.traced),
        report.errors,
    )


def run_rotation(feeds: list[Feed], every: int) -> None:
    """Ticks each feed once, in order, sleeping `every` seconds between them."""
    for feed in feeds:
        if _stop_requested:
            return
        _log_report(tick(feed.key))
        time.sleep(every)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description="The laptop clock for the live loop.")
    parser.add_argument("--every", type=int, default=45, help="seconds between feed ticks")
    parser.add_argument("--once", action="store_true", help="run a single rotation and exit")
    parser.add_argument("--platform", choices=["lemmy", "reddit", "imgflip"], default=None)
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    db.init_schema()
    feeds = _feeds_for(args.platform)
    while not _stop_requested:
        run_rotation(feeds, args.every)
        if _stop_requested:
            break
        specimens = detect_specimens()
        expired = store.expire_specimens()
        log.info("rotation done: %d specimen(s) attached, %d expired", len(specimens), len(expired))
        if args.once:
            break
    log.info("stopped")


if __name__ == "__main__":
    main()
