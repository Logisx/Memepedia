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
        nsfw=None,
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


# --- Matcher ------------------------------------------------------------------------------

KINDS = {
    "doomer": "character",
    "doomer-girl": "character",
    "wojak": "character",
    "swole-doge-vs-cheems": "template",
    "distracted-boyfriend": "template",
    "pepe-the-frog": "character",
}


@pytest.mark.parametrize(
    ("name", "node_id"),
    [
        ("doomer", "doomer"),
        ("The Doomer meme", "doomer"),
        ("feels guy", "wojak"),
        ("Buff Doge vs Cheems", "swole-doge-vs-cheems"),
        ("Doomer Wojak", None),
        ("   ", None),
    ],
)
def test_matcher_exact_agrees_with_exact_match(name: str, node_id: str | None) -> None:
    matcher = resolver.Matcher(INDEX, KINDS)
    assert matcher.exact(name) == node_id
    if name.strip():
        assert matcher.exact(name) == resolver.exact_match(INDEX, name)


def test_matcher_exact_first_duplicate_wins() -> None:
    index = [("Doge", "first"), ("doge", "second")]
    assert resolver.Matcher(index, {}).exact("DOGE") == "first"
    assert resolver.exact_match(index, "DOGE") == "first"


def test_matcher_near_without_llm_never_asks(archive: FakeArchive) -> None:
    archive.answer = "doomer"
    matcher = resolver.Matcher(INDEX, KINDS, allow_llm=False)
    assert matcher.near("Doomer Wojak", None) is None
    assert matcher.near("the doomer", None) == "doomer"
    assert archive.asked == []


def test_matcher_near_asks_once_and_remembers_the_answer(archive: FakeArchive) -> None:
    archive.answer = "doomer"
    matcher = resolver.Matcher(INDEX, KINDS)
    assert matcher.near("Doomer Wojak", "a tired figure") == "doomer"
    assert matcher.near("Doomer Wojak", "a tired figure") == "doomer"
    assert len(archive.asked) == 1
    assert matcher.exact("Doomer Wojak") == "doomer"


def test_matcher_subject_takes_the_one_character_named() -> None:
    matcher = resolver.Matcher(INDEX, KINDS)
    assert matcher.subject(["a man at a desk", "Wojak"]) == "wojak"
    assert matcher.subject(["Wojak", "Feels Guy"]) == "wojak"  # two names, one node


def test_matcher_subject_is_ambiguous_for_two_characters() -> None:
    assert resolver.Matcher(INDEX, KINDS).subject(["Wojak", "Pepe the Frog"]) is None


def test_matcher_subject_ignores_templates_and_blanks() -> None:
    matcher = resolver.Matcher(INDEX, KINDS)
    assert matcher.subject(["Distracted Boyfriend"]) is None
    assert matcher.subject(["", "  "]) is None
    assert matcher.subject([]) is None


def test_matcher_subject_is_exact_only(archive: FakeArchive) -> None:
    archive.answer = "doomer"
    assert resolver.Matcher(INDEX, KINDS).subject(["Doomer Wojak"]) is None
    assert archive.asked == []


def test_matcher_subject_skips_generic_names() -> None:
    index = [("Walter", "walter"), ("Doge", "doge"), ("Cameraman", "cameraman")]
    kinds = {"walter": "character", "doge": "character", "cameraman": "character"}
    matcher = resolver.Matcher(index, kinds)
    assert matcher.subject(["Walter"]) is None
    assert matcher.subject(["the Cameraman"]) is None
    assert matcher.subject(["Walter", "Doge"]) == "doge"


_BABY_YODA_INDEX = [
    ("Baby Yoda", "baby-yoda"),
    ("Grogu", "baby-yoda"),
    ("Chad", "chad"),
    ("Big Brain Wojak", "big-brain-wojak"),
    ("Big Brain", "big-brain-wojak"),
    ("Doge", "doge"),
]
_BABY_YODA_KINDS = {
    "baby-yoda": "character",
    "chad": "character",
    "big-brain-wojak": "character",
    "doge": "character",
}


@pytest.mark.parametrize(
    "subjects",
    [["a child", "teacher"], ["child"], ["the child", "dog"]],
)
def test_matcher_subject_does_not_stamp_baby_yoda_for_a_bare_child(
    subjects: list[str],
) -> None:
    matcher = resolver.Matcher(_BABY_YODA_INDEX, _BABY_YODA_KINDS)
    assert matcher.subject(subjects) is None


@pytest.mark.parametrize("subjects", [["Baby Yoda", "teacher"], ["Grogu"]])
def test_matcher_subject_still_stamps_baby_yoda_by_its_real_name(
    subjects: list[str],
) -> None:
    matcher = resolver.Matcher(_BABY_YODA_INDEX, _BABY_YODA_KINDS)
    assert matcher.subject(subjects) == "baby-yoda"


def test_matcher_subject_does_not_stamp_chad_or_big_brain_wojak_for_generic_subjects() -> None:
    matcher = resolver.Matcher(_BABY_YODA_INDEX, _BABY_YODA_KINDS)
    assert matcher.subject(["Chad"]) is None
    assert matcher.subject(["big brain"]) is None


def test_matcher_exact_and_near_still_stamp_chad_and_big_brain_wojak_by_guess() -> None:
    matcher = resolver.Matcher(_BABY_YODA_INDEX, _BABY_YODA_KINDS)
    assert matcher.exact("Chad") == "chad"
    assert matcher.exact("Big Brain Wojak") == "big-brain-wojak"
    assert matcher.exact("Big Brain") == "big-brain-wojak"


_TITLE_INDEX = [
    *INDEX,
    ("Jensen Huang", "jensen-huang"),
    ("Nvidia CEO", "jensen-huang"),
    ("Reaction image", "reaction-image"),
    ("Labubu", "labubu"),
]
_TITLE_KINDS = {
    **KINDS,
    "jensen-huang": "character",
    "reaction-image": "format_class",
    "labubu": "character",
}


def _title_matcher() -> resolver.Matcher:
    return resolver.Matcher(_TITLE_INDEX, _TITLE_KINDS, allow_llm=False)


def test_matcher_title_finds_a_distinctive_name() -> None:
    assert _title_matcher().title("POV: you're Jensen Huang") == "jensen-huang"
    assert _title_matcher().title("the nvidia ceo again") == "jensen-huang"


def test_matcher_title_ignores_short_single_words_and_roots() -> None:
    matcher = _title_matcher()
    assert matcher.title("Performative Huang supporter") is None  # "Huang" alone is not a name
    assert matcher.title("Doomer at 3am") is None  # one word under 8 letters
    assert matcher.title("labubu everywhere") is None
    assert matcher.title("just a reaction image") is None  # format-class roots never count


def test_matcher_title_wants_a_whole_phrase() -> None:
    assert _title_matcher().title("jensenhuang fan account") is None


def test_matcher_title_gives_none_for_two_memes() -> None:
    assert _title_matcher().title("Jensen Huang as the Distracted Boyfriend") is None


def test_matcher_title_prefers_the_longer_name_inside_it() -> None:
    index = [("Doomer Girl", "doomer-girl"), ("Doomer Girl Variant", "dgv")]
    matcher = resolver.Matcher(index, {"doomer-girl": "character", "dgv": "character"})
    assert matcher.title("a doomer girl variant appears") == "dgv"
