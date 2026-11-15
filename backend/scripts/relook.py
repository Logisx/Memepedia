"""Look again at sightings the live loop could not stamp properly.

Three targets, one per run:
- default: sightings whose image was never read (no vision label). The dry run downloads and
  decodes each image (no paid calls) and says which now work. With `--apply`, up to `--max`
  of them are labelled (one Gemini call and one Gemma guardrail call each), matched and saved.
- `--not-memes`: sightings the vision model called "not a meme" under the old, stricter prompt;
  `--apply` labels them again with the current prompt (same cost per image).
- `--orphans`: unstamped sightings the vision model did call a meme, left "unclassified" when
  their specimen expired; `--apply` sets them back to pending. No paid calls.

Reposts (`duplicate_of` set) are never touched: they follow their original.

Usage: uv run python scripts/relook.py [--apply] [--max 80] [--not-memes | --orphans]

With a repo-root `.env` holding DATABASE_URL this targets the hosted (production) database;
the target is printed before anything else happens.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from memepedia import db, live, llm, store
from memepedia.config import get_settings
from memepedia.live import Thresholds, classify
from memepedia.resolver import Matcher

DEFAULT_MAX = 80
Mode = Literal["unread", "not-memes", "orphans"]

_TARGETS: dict[Mode, str] = {
    "unread": "vision IS NULL",
    "not-memes": "state = 'unclassified' AND vision IS NOT NULL AND (vision->>'is_meme') = 'false'",
    "orphans": "state = 'unclassified' AND node_id IS NULL AND (vision->>'is_meme') = 'true'",
}


@dataclass
class RelookReport:
    """What a run found and did."""

    mode: Mode
    examined: int = 0
    outcomes: Counter[str] = field(default_factory=Counter)
    lines: list[str] = field(default_factory=list)
    changed: int = 0
    stopped: str | None = None


def targets(mode: Mode) -> list[db.Row]:
    """The sightings one mode looks at, newest first; never reposts."""
    return db.fetch_all(
        "SELECT id, image_url, title, state, node_id FROM sightings"
        f" WHERE duplicate_of IS NULL AND {_TARGETS[mode]} ORDER BY posted_at DESC"
    )


def _restore_orphans(rows: list[db.Row], apply: bool, report: RelookReport) -> None:
    for row in rows:
        report.lines.append(f"{row['id']}  pending  {row['title'][:60]}")
    report.outcomes["to pending"] = len(rows)
    if apply:
        report.changed = store.set_sighting_state([r["id"] for r in rows], "pending")


def _relabel(rows: list[db.Row], apply: bool, max_n: int, report: RelookReport) -> None:
    thresholds = Thresholds.from_settings(get_settings())
    matcher = Matcher.from_store(allow_llm=False)
    roots, known_names = live._archive_context()
    labelled = 0
    for row in rows:
        url = live.readable_image_url(row["image_url"])
        moved = "" if url == row["image_url"] else f"  (from {row['image_url']})"
        fetched = live.fetch_image(url)
        if fetched.prepared is None:
            reason = fetched.error or "unreadable"
            report.outcomes[reason] += 1
            report.lines.append(f"{row['id']}  {reason:16s} {url}")
            if apply:
                store.set_image_check(row["id"], None, reason)
            continue
        if not apply:
            report.outcomes["ok"] += 1
            report.lines.append(f"{row['id']}  {'ok':16s} {url}{moved}")
            continue
        if labelled >= max_n:
            report.outcomes["over --max"] += 1
            continue
        image = fetched.prepared
        try:
            vision = llm.vision_label(
                image.data, image.mime, title=row["title"], roots=roots, known_names=known_names
            )
        except llm.GeminiCapReached as exc:
            report.stopped = str(exc)
            return
        except llm.LLMError as exc:
            report.outcomes["vision error"] += 1
            report.lines.append(f"{row['id']}  vision error     {exc}")
            continue
        labelled += 1
        vision = live._guardrail(image.data, image.mime, vision)
        node_id, state = classify(vision, thresholds, matcher, row["title"])
        store.update_sighting_label(
            row["id"], vision, node_id, state, image_url=url, fingerprint=image.fingerprint
        )
        report.changed += 1
        report.outcomes[state] += 1
        stamp = node_id or "-"
        report.lines.append(f"{row['id']}  {state:16s} {stamp:28s} {row['title'][:50]}")


def relook(mode: Mode, apply: bool, max_n: int = DEFAULT_MAX) -> RelookReport:
    """Runs one mode; changes nothing unless `apply`."""
    report = RelookReport(mode)
    rows = targets(mode)
    report.examined = len(rows)
    if mode == "orphans":
        _restore_orphans(rows, apply, report)
    else:
        _relabel(rows, apply, max_n, report)
    return report


def _print_report(report: RelookReport, apply: bool) -> None:
    for line in report.lines:
        print(line)
    print(f"\n{report.mode}: examined {report.examined} sightings")
    for outcome, count in report.outcomes.most_common():
        print(f"  {count:4d}  {outcome}")
    if report.stopped:
        print(f"stopped early: {report.stopped}")
    print(f"changed: {report.changed}" if apply else "dry run: nothing changed (add --apply)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Look again at badly stamped sightings.")
    parser.add_argument("--apply", action="store_true", help="save the results (default: dry run)")
    parser.add_argument("--max", type=int, default=DEFAULT_MAX, help="images to label at most")
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--not-memes", action="store_true", help="re-label 'not a meme' posts")
    which.add_argument("--orphans", action="store_true", help="expired specimens' memes to pending")
    args = parser.parse_args()
    mode: Mode = "not-memes" if args.not_memes else "orphans" if args.orphans else "unread"

    print(f"database: {db.describe_target()}")
    db.init_schema()
    report = relook(mode, args.apply, args.max)
    _print_report(report, args.apply)


if __name__ == "__main__":
    main()
