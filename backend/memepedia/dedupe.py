"""When two sightings are the same post: the duplicate rule, pure and unit-tested.

The same picture reaches the archive under different post URLs: one account cross-posting to two
Lemmy instances (byte-identical image URL), or one Reddit user posting to r/memes and r/dankmemes
(a fresh upload each time, so only the pixels match). Titles alone are not a key: dozens of
different r/me_irl posts are all titled "me_irl". The rules, first match wins:

- D1: the image URL is identical;
- D2: the fingerprints are within `NEAR_IDENTICAL` bits of 256, and the posts are no more than
  `WINDOW` apart;
- D3: the fingerprints are within `SIMILAR` bits, AND the posts share a non-null author or a
  non-generic title, AND they are no more than `WINDOW` apart.

No I/O: callers load the candidates (`store.dedupe_candidates`) and store the verdict.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from memepedia import imageprep

NEAR_IDENTICAL = 4
SIMILAR = 12
WINDOW = timedelta(days=7)
GENERIC_TITLES = frozenset(
    {"", "me irl", "meirl", "me_irl", ".", "meme", "memes", "dankmemes", "title", "untitled"}
)

Rule = Literal["D1", "D2", "D3"]

_NON_WORD = re.compile(r"[^a-z0-9_]+")


@dataclass(frozen=True)
class Candidate:
    """One sighting, reduced to what the duplicate rule looks at."""

    id: str
    image_url: str
    fingerprint: str | None
    author: str | None
    title: str
    posted_at: datetime


@dataclass(frozen=True)
class Match:
    """Which earlier sighting a post repeats, and why."""

    original: Candidate
    rule: Rule
    bits: int | None


def norm_title(title: str) -> str:
    """Lowercase, punctuation to spaces; "" for a title that says nothing (e.g. "me_irl")."""
    words = " ".join(_NON_WORD.sub(" ", title.lower()).split())
    return "" if words in GENERIC_TITLES or words.replace(" ", "_") in GENERIC_TITLES else words


def compare(a: Candidate, b: Candidate) -> Match | None:
    """Whether `a` repeats `b` (D1, D2 or D3), as a Match against `b`; None when it does not."""
    if a.image_url == b.image_url:
        return Match(b, "D1", None)
    if a.fingerprint is None or b.fingerprint is None:
        return None
    if abs(a.posted_at - b.posted_at) > WINDOW:
        return None
    bits = imageprep.distance(a.fingerprint, b.fingerprint)
    if bits <= NEAR_IDENTICAL:
        return Match(b, "D2", bits)
    if bits <= SIMILAR:
        same_author = a.author is not None and a.author == b.author
        title = norm_title(a.title)
        same_title = bool(title) and title == norm_title(b.title)
        if same_author or same_title:
            return Match(b, "D3", bits)
    return None


def same_post(a: Candidate, b: Candidate) -> bool:
    """Whether two sightings are one post seen twice."""
    return compare(a, b) is not None


def find_original(c: Candidate, others: Iterable[Candidate]) -> Match | None:
    """The earliest-posted of `others` that `c` repeats (ties: the smaller id), or None."""
    matches = [m for other in others if other.id != c.id and (m := compare(c, other))]
    if not matches:
        return None
    return min(matches, key=lambda m: (m.original.posted_at, m.original.id))


def candidate(row: Mapping[str, Any]) -> Candidate:
    """A Candidate from a sightings row (as `store.dedupe_candidates` returns them)."""
    return Candidate(
        id=row["id"],
        image_url=row["image_url"],
        fingerprint=row.get("fingerprint"),
        author=row.get("author"),
        title=row.get("title") or "",
        posted_at=row["posted_at"],
    )
