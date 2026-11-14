"""Re-match pending sightings against the archive as it is now, using their saved vision labels.

A dry run by default: it prints what it would stamp and changes nothing. It makes no Gemini
call unless `--llm` is given, and then at most `--max-llm` guesses go to the near-match check.

Usage: uv run python scripts/rematch.py [--apply] [--hours N] [--llm] [--max-llm 50]

With a repo-root `.env` holding DATABASE_URL this targets the hosted (production) database;
the target is printed before anything else happens.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field

from memepedia import db, llm, resolver, store
from memepedia.config import get_settings
from memepedia.live import LabelMatch, Thresholds, match_label
from memepedia.models import VisionLabel
from memepedia.resolver import Matcher

DEFAULT_MAX_LLM = 50


@dataclass(frozen=True)
class Proposal:
    """One pending sighting that now points at an archive node."""

    sighting_id: str
    node_id: str
    via: str
    detail: str


@dataclass
class RematchReport:
    """What a re-match run found and did."""

    examined: int = 0
    proposals: list[Proposal] = field(default_factory=list)
    llm_used: int = 0
    llm_skipped: int = 0
    applied: int = 0


def _needs_llm(label: VisionLabel, thresholds: Thresholds, matcher: Matcher) -> bool:
    """Whether matching this label would put its guess to the near-match LLM check."""
    guess = label.template_guess
    return bool(
        label.is_meme
        and guess
        and label.confidence >= thresholds.near
        and matcher.exact(guess) is None
        and resolver.closest(matcher.index, guess)
    )


def _detail(label: VisionLabel, match: LabelMatch) -> str:
    if match.via == "subject":
        return ", ".join(label.subjects)
    return label.template_guess or ""


def rematch(apply: bool, hours: int | None, llm_enabled: bool, max_llm: int) -> RematchReport:
    """Match every pending sighting that has a vision label; stamp them only when `apply`."""
    thresholds = Thresholds.from_settings(get_settings())
    base = Matcher.from_store(allow_llm=False)
    with_llm = Matcher(base.index, base.kinds, allow_llm=True)
    report = RematchReport()
    for row in store.pending_with_vision(hours):
        report.examined += 1
        label = llm.parse_stored_vision(row["vision"])
        if not label.is_meme:
            continue
        matcher = base
        if _needs_llm(label, thresholds, base):
            if llm_enabled and report.llm_used < max_llm:
                report.llm_used += 1
                matcher = with_llm
            else:
                report.llm_skipped += 1
        match = match_label(label, thresholds, matcher)
        if match is not None:
            detail = _detail(label, match)
            report.proposals.append(Proposal(row["id"], match.node_id, match.via, detail))
    if apply:
        report.applied = _apply(report.proposals)
    return report


def _apply(proposals: list[Proposal]) -> int:
    by_node: dict[str, list[str]] = {}
    for proposal in proposals:
        by_node.setdefault(proposal.node_id, []).append(proposal.sighting_id)
    return sum(store.attach_sightings(ids, node_id) for node_id, ids in by_node.items())


def _print_report(report: RematchReport, apply: bool, llm_enabled: bool) -> None:
    for p in report.proposals:
        print(f"{p.sighting_id}  {p.node_id:32s} {p.via:8s} {p.detail}")
    print(f"\nexamined {report.examined} pending sightings, {len(report.proposals)} would match")
    for node_id, count in Counter(p.node_id for p in report.proposals).most_common():
        print(f"  {count:4d}  {node_id}")
    for via, count in Counter(p.via for p in report.proposals).most_common():
        print(f"  via {via}: {count}")
    if llm_enabled:
        print(
            f"near-match LLM checks used: {report.llm_used}, "
            f"skipped over the cap: {report.llm_skipped}"
        )
    elif report.llm_skipped:
        print(f"{report.llm_skipped} more guesses need the near-match LLM check: rerun with --llm")
    print(f"stamped: {report.applied}" if apply else "dry run: nothing changed (add --apply)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-match pending sightings to the archive.")
    parser.add_argument("--apply", action="store_true", help="stamp the matches (default: dry run)")
    parser.add_argument("--hours", type=int, default=None, help="only sightings seen this recently")
    parser.add_argument("--llm", action="store_true", help="allow near-match LLM checks")
    parser.add_argument("--max-llm", type=int, default=DEFAULT_MAX_LLM)
    args = parser.parse_args()

    print(f"database: {db.describe_target()}")
    db.init_schema()
    report = rematch(args.apply, args.hours, args.llm, args.max_llm)
    _print_report(report, args.apply, args.llm)


if __name__ == "__main__":
    main()
