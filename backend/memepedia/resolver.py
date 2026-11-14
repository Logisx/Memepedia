"""Identity: map a name to an existing archive node, or decide that it is new.

Every write path goes through here; without it "Doomer", "Doomer Wojak" and
"Wojak (Doomer)" become three nodes. Only an exact match after normalisation is
automatic. A near match is put to the LLM, because string distance cannot tell
an alias ("Doomer Wojak") from a different meme ("Doomer Girl").
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from rapidfuzz import fuzz

from memepedia import llm, store

NameIndex = Sequence[tuple[str, str]]

NEAR_SCORE = 60.0
MAX_CANDIDATES = 10
_FILLER = re.compile(r"\b(the|a|an|meme|memes|template|format)\b")
_NON_WORD = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Match:
    """An archive node whose name or alias is close to the name being resolved."""

    node_id: str
    score: float


def normalize(name: str) -> str:
    """Lowercase, strip accents, punctuation and filler words such as "meme"."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    words = _NON_WORD.sub(" ", ascii_name.lower().replace("&", " and "))
    stripped = " ".join(_FILLER.sub(" ", words).split())
    return stripped or " ".join(words.split())


def slugify(name: str) -> str:
    """URL-safe node id for a name, e.g. "Swole Doge vs. Cheems" -> "swole-doge-vs-cheems"."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return _NON_WORD.sub("-", ascii_name.lower()).strip("-") or "unnamed"


def exact_match(index: NameIndex, name: str) -> str | None:
    """Node id whose name or alias equals `name` after normalisation."""
    wanted = normalize(name)
    return next((node_id for known, node_id in index if normalize(known) == wanted), None)


def closest(index: NameIndex, name: str, limit: int = MAX_CANDIDATES) -> list[Match]:
    """The nodes with the nearest names, best first, one entry per node."""
    wanted = normalize(name)
    best: dict[str, float] = {}
    for known, node_id in index:
        score = float(fuzz.WRatio(wanted, normalize(known)))
        if score >= NEAR_SCORE and score > best.get(node_id, 0.0):
            best[node_id] = score
    ranked = sorted(best.items(), key=lambda item: (-item[1], item[0]))
    return [Match(node_id, score) for node_id, score in ranked[:limit]]


def _ask_llm(name: str, hint: str | None, matches: Sequence[Match]) -> str | None:
    nodes = store.get_nodes([match.node_id for match in matches])
    candidates = [llm.Candidate(n.id, n.name, n.kind, tuple(n.aliases)) for n in nodes]
    chosen = llm.same_or_new(name, hint=hint, candidates=candidates)
    return chosen if chosen in {n.id for n in nodes} else None


def resolve(name: str, *, hint: str | None = None, allow_llm: bool = True) -> str | None:
    """Return the id of the archive node that `name` refers to, or None when it is new.

    A match confirmed by the LLM is remembered as an alias, so it is exact next time.
    """
    if not name.strip():
        return None
    index = store.name_index()
    if (node_id := exact_match(index, name)) is not None:
        return node_id
    matches = closest(index, name)
    if not matches or not allow_llm:
        return None
    chosen = _ask_llm(name, hint, matches)
    if chosen is not None:
        store.add_alias(chosen, name.strip())
    return chosen


def free_id(name: str) -> str:
    """A node id for a new meme called `name` that no existing node uses."""
    base = slugify(name)
    candidate, suffix = base, 2
    while store.get_node(candidate) is not None:
        candidate, suffix = f"{base}-{suffix}", suffix + 1
    return candidate
