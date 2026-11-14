"""Identity: map a name to an existing archive node, or decide that it is new.

Every write path goes through here; without it "Doomer", "Doomer Wojak" and
"Wojak (Doomer)" become three nodes. Only an exact match after normalisation is
automatic. A near match is put to the LLM, because string distance cannot tell
an alias ("Doomer Wojak") from a different meme ("Doomer Girl").
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
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


def _resolve_in(index: NameIndex, name: str, hint: str | None, allow_llm: bool) -> str | None:
    """The body of `resolve`, against an index the caller has already loaded."""
    if not name.strip():
        return None
    if (node_id := exact_match(index, name)) is not None:
        return node_id
    matches = closest(index, name)
    if not matches or not allow_llm:
        return None
    chosen = _ask_llm(name, hint, matches)
    if chosen is not None:
        store.add_alias(chosen, name.strip())
    return chosen


def resolve(name: str, *, hint: str | None = None, allow_llm: bool = True) -> str | None:
    """Return the id of the archive node that `name` refers to, or None when it is new.

    A match confirmed by the LLM is remembered as an alias, so it is exact next time.
    """
    return _resolve_in(store.name_index(), name, hint, allow_llm)


# One-word character names that are also ordinary words (a job, a food, a first name, a game
# term, a kinship term), so a depicted "cameraman", "Walter" or "child" must never stamp a
# sighting on its own. This set only governs the subject rule (Matcher.subject), never the
# template-guess rules (Matcher.exact / Matcher.near), so it is also safe to list generic
# forms of legitimate character names here: "chad" and "big brain" stop a bare vision-subject
# from stamping chad/big-brain-wojak, while a post whose own template guess is "Chad" or
# "Big Brain Wojak" still resolves normally.
_GENERIC_SUBJECTS = frozenset(
    {"cameraman", "cameramen", "haggis", "walter", "npc", "child", "chad", "big brain"}
)


def is_generic_subject(name: str) -> bool:
    """Whether `name` is too generic to name a character on its own (see `_GENERIC_SUBJECTS`)."""
    return normalize(name) in _GENERIC_SUBJECTS


class Matcher:
    """Name lookups for one batch of labels, with the archive's names loaded once."""

    def __init__(
        self, index: NameIndex, kinds: Mapping[str, str], *, allow_llm: bool = True
    ) -> None:
        self.index = index
        self.kinds = kinds
        self.allow_llm = allow_llm
        self._exact: dict[str, str] = {}
        for known, node_id in index:
            self._exact.setdefault(normalize(known), node_id)  # first one wins, as exact_match

    @classmethod
    def from_store(cls, *, allow_llm: bool = True) -> Matcher:
        """A matcher over the archive as it is now."""
        return cls(store.name_index(), store.node_kinds(), allow_llm=allow_llm)

    def exact(self, name: str) -> str | None:
        """Node id whose name or alias equals `name` after normalisation."""
        return self._exact.get(normalize(name)) if name.strip() else None

    def near(self, name: str, hint: str | None) -> str | None:
        """Exact match, else a near match confirmed by the LLM (never asked when it is off)."""
        if (known := self.exact(name)) is not None:
            return known
        node_id = _resolve_in(self.index, name, hint, self.allow_llm)
        if node_id is not None:
            self._exact.setdefault(normalize(name), node_id)  # an LLM-confirmed alias is exact now
        return node_id

    def subject(self, subjects: Sequence[str]) -> str | None:
        """The one character node the depicted subjects name exactly; None if none or several.

        Subjects are free text, so only exact names count: no fuzzy match and no LLM call.
        """
        found: set[str] = set()
        for subject in subjects:
            if not subject.strip() or normalize(subject) in _GENERIC_SUBJECTS:
                continue
            node_id = self.exact(subject)
            if node_id is not None and self.kinds.get(node_id) == "character":
                found.add(node_id)
        return next(iter(found)) if len(found) == 1 else None


def free_id(name: str) -> str:
    """A node id for a new meme called `name` that no existing node uses."""
    base = slugify(name)
    candidate, suffix = base, 2
    while store.get_node(candidate) is not None:
        candidate, suffix = f"{base}-{suffix}", suffix + 1
    return candidate
