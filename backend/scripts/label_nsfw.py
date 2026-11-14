"""Backfill the nsfw label for every node image and every unlabelled sighting.

One small Gemini vision call per image, a few workers at a time, reusing the existing
retry/timeout in memepedia.llm. Idempotent: only NULL rows are labelled unless --relabel.
Unreachable images are left NULL (they stay hidden on the wall / blurred in the archive).

Usage: uv run python scripts/label_nsfw.py [--relabel] [--dry-run] [--workers N]
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal

from memepedia import db, llm, store
from memepedia.live import _download_image
from memepedia.models import MemeNode

log = logging.getLogger("memepedia.label_nsfw")

_MAX_WORKERS = 3


@dataclass(frozen=True)
class Outcome:
    """One row's labelling result; nsfw is None when its image could not be fetched or read."""

    kind: Literal["node", "sighting"]
    id: str
    nsfw: bool | None


def _label_image_url(image_url: str) -> bool | None:
    """Downloads one image and labels it nsfw; None if it could not be fetched or labelled."""
    downloaded = _download_image(image_url)
    if downloaded is None:
        return None
    data, mime = downloaded
    try:
        nsfw, _reason = llm.label_nsfw_only(data, mime)
    except llm.LLMError:
        log.warning("nsfw labelling failed for %s", image_url, exc_info=True)
        return None
    return nsfw


def _label_node(node: MemeNode) -> Outcome:
    assert node.image_url is not None
    return Outcome("node", node.id, _label_image_url(node.image_url))


def _label_sighting(row: db.Row) -> Outcome:
    return Outcome("sighting", row["id"], _label_image_url(row["image_url"]))


def _apply(outcomes: Sequence[Outcome]) -> None:
    for outcome in outcomes:
        if outcome.nsfw is None:
            continue
        if outcome.kind == "node":
            store.set_node_nsfw(outcome.id, outcome.nsfw)
        else:
            store.set_sighting_nsfw(outcome.id, outcome.nsfw)


def run(*, relabel: bool, dry_run: bool, workers: int) -> list[Outcome]:
    """Labels every qualifying node and sighting image; writes results unless `dry_run`."""
    nodes = store.nodes_needing_nsfw_label(relabel)
    sightings = store.sightings_needing_nsfw_label(relabel)
    with ThreadPoolExecutor(max_workers=max(1, min(workers, _MAX_WORKERS))) as pool:
        node_futures = [pool.submit(_label_node, n) for n in nodes]
        sighting_futures = [pool.submit(_label_sighting, s) for s in sightings]
        outcomes = [f.result() for f in node_futures] + [f.result() for f in sighting_futures]
    if not dry_run:
        _apply(outcomes)
    return outcomes


def _summarize(outcomes: Sequence[Outcome]) -> None:
    for kind in ("node", "sighting"):
        rows = [o for o in outcomes if o.kind == kind]
        true_n = sum(1 for o in rows if o.nsfw is True)
        false_n = sum(1 for o in rows if o.nsfw is False)
        null_n = sum(1 for o in rows if o.nsfw is None)
        print(f"{kind}s: nsfw=true {true_n}, nsfw=false {false_n}, still null {null_n}")
    flagged = sorted(o.id for o in outcomes if o.kind == "node" and o.nsfw is True)
    if flagged:
        print("flagged node ids:")
        for node_id in flagged:
            print(f"  - {node_id}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description="Label every unlabelled node/sighting image.")
    parser.add_argument(
        "--relabel", action="store_true", help="Relabel every row, not just the unlabelled ones."
    )
    parser.add_argument("--dry-run", action="store_true", help="Label but do not write results.")
    parser.add_argument("--workers", type=int, default=_MAX_WORKERS)
    args = parser.parse_args()
    db.init_schema()
    outcomes = run(relabel=args.relabel, dry_run=args.dry_run, workers=args.workers)
    _summarize(outcomes)
    if args.dry_run:
        print("(dry run: no rows were written)")


if __name__ == "__main__":
    main()
