"""Mark the reposts already in the archive: the same picture saved under two post URLs.

First every sighting without an image fingerprint gets one: its image is downloaded and decoded
(no paid calls), and the fingerprint, or why the image could not be read, is saved. That runs in
both modes, because it only adds data. Then sightings are grouped with the live loop's own rule
(`memepedia.dedupe`). In each group the keeper is the best stamped (resolved, then pending, then
unclassified), then the earliest posted. With `--apply` the others become reposts of it: they
take its stamp and leave the wall, the counts and the clustering.

Usage: uv run python scripts/dedupe.py [--apply] [--workers 8]

With a repo-root `.env` holding DATABASE_URL this targets the hosted (production) database;
the target is printed before anything else happens.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from memepedia import db, dedupe, live, store

DEFAULT_WORKERS = 8
_STATE_RANK = {"resolved": 0, "pending": 1, "unclassified": 2}


@dataclass
class Group:
    """One picture seen several times: the sighting kept and the reposts of it."""

    keeper: db.Row
    # The match says why a repost belongs here; None when it is only linked through another one.
    reposts: list[tuple[db.Row, dedupe.Match | None]] = field(default_factory=list)


@dataclass
class DedupeReport:
    """What a run found and did."""

    fingerprinted: int = 0
    unreadable: int = 0
    groups: list[Group] = field(default_factory=list)
    marked: int = 0


def _rows_without_fingerprint() -> list[db.Row]:
    return db.fetch_all(
        "SELECT id, image_url FROM sightings"
        " WHERE duplicate_of IS NULL AND fingerprint IS NULL ORDER BY posted_at"
    )


def backfill_fingerprints(
    report: DedupeReport,
    workers: int,
    fetch: Callable[[str], live.Fetched] = live.fetch_image,
) -> None:
    """Downloads every unfingerprinted image and saves its fingerprint or its look_error."""
    rows = _rows_without_fingerprint()
    print(f"fingerprinting {len(rows)} images")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(lambda r: (r, fetch(live.readable_image_url(r["image_url"]))), rows)
        for done, (row, fetched) in enumerate(results, start=1):
            if fetched.prepared is not None:
                store.set_image_check(row["id"], fetched.prepared.fingerprint, None)
                report.fingerprinted += 1
            else:
                store.set_image_check(row["id"], None, fetched.error)
                report.unreadable += 1
            if done % 50 == 0:
                print(f"  {done}/{len(rows)}")


def _keeper(rows: Sequence[db.Row]) -> db.Row:
    return min(rows, key=lambda r: (_STATE_RANK.get(r["state"], 9), r["posted_at"], r["id"]))


def find_groups(rows: Sequence[db.Row]) -> list[Group]:
    """Groups rows (oldest first) by the duplicate rule; only groups of two or more."""
    ordered = sorted(rows, key=lambda r: (r["posted_at"], r["id"]))
    group_of: dict[str, str] = {}  # sighting id -> id of the first row of its group
    members: dict[str, list[tuple[db.Row, dedupe.Match | None]]] = {}
    walked: list[dedupe.Candidate] = []
    for row in ordered:
        candidate = dedupe.candidate(row)
        match = dedupe.find_original(candidate, walked)
        root = group_of[match.original.id] if match else row["id"]
        group_of[row["id"]] = root
        members.setdefault(root, []).append((row, match))
        walked.append(candidate)
    groups = []
    for entries in members.values():
        if len(entries) < 2:
            continue
        keeper = _keeper([r for r, _ in entries])
        group = Group(keeper)
        for row, match in entries:
            if row["id"] == keeper["id"]:
                continue
            # The group's first row has no match of its own: describe it against the keeper.
            found = match or dedupe.compare(dedupe.candidate(keeper), dedupe.candidate(row))
            group.reposts.append((row, found))
        groups.append(group)
    return groups


def _all_originals() -> list[db.Row]:
    return db.fetch_all(
        "SELECT id, image_url, fingerprint, author, title, posted_at, state, node_id, post_url"
        " FROM sightings WHERE duplicate_of IS NULL ORDER BY posted_at, id"
    )


def dedupe_archive(
    apply: bool, workers: int, fetch: Callable[[str], live.Fetched] = live.fetch_image
) -> DedupeReport:
    """Fingerprints, groups and (with `apply`) marks the archive's reposts."""
    report = DedupeReport()
    backfill_fingerprints(report, workers, fetch)
    report.groups = find_groups(_all_originals())
    if apply:
        for group in report.groups:
            ids = [row["id"] for row, _ in group.reposts]
            report.marked += store.mark_duplicates(group.keeper["id"], ids)
    return report


def _line(row: db.Row) -> str:
    return f"{row['id']}  {row['state']:12s} {row['author'] or '-':20.20s} {row['post_url']}"


def _print_report(report: DedupeReport, apply: bool) -> None:
    print(f"fingerprinted: {report.fingerprinted}, unreadable: {report.unreadable}")
    for group in report.groups:
        print(f"\nkeep   {_line(group.keeper)}")
        for row, match in group.reposts:
            if match is None:
                why = "linked"
            else:
                why = match.rule + ("" if match.bits is None else f" ({match.bits} bits)")
            print(f"  {why:14s} {_line(row)}")
    reposts = sum(len(g.reposts) for g in report.groups)
    print(f"\n{len(report.groups)} groups, {reposts} reposts")
    print(f"marked: {report.marked}" if apply else "dry run: no repost marked (add --apply)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Mark reposts already in the archive.")
    parser.add_argument("--apply", action="store_true", help="mark the reposts (default: dry run)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    args = parser.parse_args()

    print(f"database: {db.describe_target()}")
    db.init_schema()
    report = dedupe_archive(args.apply, args.workers)
    _print_report(report, args.apply)


if __name__ == "__main__":
    main()
