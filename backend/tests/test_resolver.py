"""Identity rules: exact matches are automatic, near matches go to the LLM, the rest are new."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from memepedia import resolver
from memepedia.llm import Candidate
from memepedia.models import MemeNode

INDEX = [
    ("Doomer", "doomer"),
    ("Doomer Girl", "doomer-girl"),
    ("Wojak", "wojak"),
    ("Feels Guy", "wojak"),
    ("Swole Doge vs. Cheems", "swole-doge-vs-cheems"),
    ("Buff Doge vs. Cheems", "swole-doge-vs-cheems"),
    ("Distracted Boyfriend", "distracted-boyfriend"),
    ("Pepe the Frog", "pepe-the-frog"),
]


def _node(node_id: str, name: str) -> MemeNode:
    return MemeNode(
        id=node_id,
        name=name,
        aliases=[],
        kind="character",
        latin_name=None,
        image_url=None,
        image_credit_url=None,
        first_seen=None,
        date_precision=None,
        summary=None,
        status="established",
        sightings_24h=0,
        sightings_7d=0,
    )


class FakeArchive:
    """Stands in for the store and the LLM; records what the resolver asked and wrote."""

    def __init__(self, answer: str | None = None) -> None:
        self.answer = answer
        self.asked: list[tuple[str, list[str]]] = []
        self.aliases: list[tuple[str, str]] = []

    def name_index(self) -> list[tuple[str, str]]:
        return INDEX

    def get_nodes(self, ids: Sequence[str]) -> list[MemeNode]:
        names = {node_id: name for name, node_id in reversed(INDEX)}
        return [_node(node_id, names[node_id]) for node_id in ids]

    def get_node(self, node_id: str) -> MemeNode | None:
        return _node(node_id, node_id) if node_id in {i for _, i in INDEX} else None

    def add_alias(self, node_id: str, alias: str) -> None:
        self.aliases.append((node_id, alias))

    def same_or_new(
        self, name: str, *, hint: str | None, candidates: Sequence[Candidate]
    ) -> str | None:
        self.asked.append((name, [candidate.id for candidate in candidates]))
        return self.answer


@pytest.fixture
def archive(monkeypatch: pytest.MonkeyPatch) -> FakeArchive:
    fake = FakeArchive()
    for name in ("name_index", "get_nodes", "get_node", "add_alias"):
        monkeypatch.setattr(resolver.store, name, getattr(fake, name))
    monkeypatch.setattr(resolver.llm, "same_or_new", fake.same_or_new)
    return fake


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Distracted Boyfriend Meme", "distracted boyfriend"),
        ("The Doomer", "doomer"),
        ("Swole Doge vs. Cheems", "swole doge vs cheems"),
        ("  PEPE   the frog ", "pepe frog"),
        ("Pokémon & Friends", "pokemon and friends"),
        ("Meme", "meme"),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert resolver.normalize(raw) == expected


def test_slugify_matches_archive_ids() -> None:
    assert resolver.slugify("Swole Doge vs. Cheems") == "swole-doge-vs-cheems"
    assert resolver.slugify("Pepe the Frog") == "pepe-the-frog"
    assert resolver.slugify("!!!") == "unnamed"


@pytest.mark.parametrize(
    ("name", "node_id"),
    [
        ("doomer", "doomer"),
        ("The Doomer meme", "doomer"),
        ("feels guy", "wojak"),
        ("Buff Doge vs Cheems", "swole-doge-vs-cheems"),
        ("distracted boyfriend template", "distracted-boyfriend"),
    ],
)
def test_exact_match_ignores_case_punctuation_and_filler(name: str, node_id: str) -> None:
    assert resolver.exact_match(INDEX, name) == node_id


def test_exact_match_does_not_confuse_a_variant_with_its_parent() -> None:
    assert resolver.exact_match(INDEX, "Doomer Wojak") is None
    assert resolver.exact_match(INDEX, "Doomer Girl") == "doomer-girl"


def test_closest_ranks_near_names_once_per_node() -> None:
    matches = resolver.closest(INDEX, "Doomer Wojak")
    ids = [match.node_id for match in matches]
    assert {"doomer", "wojak"} <= set(ids)
    assert len(ids) == len(set(ids))
    assert matches == sorted(matches, key=lambda m: -m.score)


def test_closest_is_empty_for_an_unrelated_name() -> None:
    assert resolver.closest(INDEX, "Xqzv Blorptangle") == []


def test_resolve_exact_needs_no_llm(archive: FakeArchive) -> None:
    assert resolver.resolve("the doomer") == "doomer"
    assert archive.asked == []
    assert archive.aliases == []


def test_resolve_near_match_asks_the_llm_and_remembers_the_alias(archive: FakeArchive) -> None:
    archive.answer = "doomer"
    assert resolver.resolve("Doomer Wojak") == "doomer"
    assert archive.asked and "doomer" in archive.asked[0][1]
    assert archive.aliases == [("doomer", "Doomer Wojak")]


def test_resolve_near_match_judged_new(archive: FakeArchive) -> None:
    archive.answer = None
    assert resolver.resolve("Doomer Boy") is None
    assert archive.aliases == []


def test_resolve_rejects_an_id_the_llm_invented(archive: FakeArchive) -> None:
    archive.answer = "not-a-candidate"
    assert resolver.resolve("Doomer Wojak") is None
    assert archive.aliases == []


def test_resolve_without_llm_or_candidates(archive: FakeArchive) -> None:
    assert resolver.resolve("Doomer Wojak", allow_llm=False) is None
    assert resolver.resolve("Xqzv Blorptangle") is None
    assert resolver.resolve("   ") is None
    assert archive.asked == []


def test_free_id_avoids_existing_nodes(archive: FakeArchive) -> None:
    assert resolver.free_id("Doomer") == "doomer-2"
    assert resolver.free_id("Grug") == "grug"
