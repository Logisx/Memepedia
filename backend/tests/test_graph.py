"""Pure-logic tests for memepedia.graph: no database involved."""

from __future__ import annotations

from datetime import date

from memepedia import graph
from memepedia.models import Axis, Kind, Link, MemeNode


def node(
    id: str,
    kind: Kind = "character",
    first_seen: str | None = None,
    precision: str | None = None,
) -> MemeNode:
    return MemeNode(
        id=id,
        name=id.replace("-", " ").title(),
        aliases=[],
        kind=kind,
        latin_name=None,
        image_url=None,
        image_credit_url=None,
        first_seen=date.fromisoformat(first_seen) if first_seen else None,
        date_precision=precision,  # type: ignore[arg-type]
        summary=None,
        status="established",
        sightings_24h=0,
        sightings_7d=0,
    )


def link(child: str, parent: str, axis: Axis = "character") -> Link:
    return Link(
        child_id=child,
        parent_id=parent,
        axis=axis,
        status="inferred",
        quote=None,
        source_url=None,
        source_title=None,
    )


WOJAK_LINKS = [
    link("wojak", "drawn-character"),
    link("doomer", "wojak"),
    link("doomer-girl", "doomer"),
    link("yes-chad", "wojak"),
]


def test_descent_follows_chain_to_root() -> None:
    assert graph.descent(WOJAK_LINKS, "doomer-girl", "character") == [
        "doomer-girl",
        "doomer",
        "wojak",
        "drawn-character",
    ]


def test_descent_with_no_parent_gives_singleton() -> None:
    assert graph.descent(WOJAK_LINKS, "drawn-character", "character") == ["drawn-character"]


def test_descent_terminates_on_cycle() -> None:
    cyclic = [link("a", "b"), link("b", "a")]
    assert graph.descent(cyclic, "a", "character") == ["a", "b"]


def test_family_ids_excludes_format_class_and_includes_whole_component() -> None:
    kinds: dict[str, Kind] = {
        "drawn-character": "format_class",
        "wojak": "character",
        "doomer": "character",
        "doomer-girl": "character",
        "yes-chad": "character",
    }
    family = graph.family_ids(WOJAK_LINKS, kinds, "doomer")
    assert family[0] == "wojak"
    assert set(family) == {"wojak", "doomer", "doomer-girl", "yes-chad"}
    assert "drawn-character" not in family


def test_family_ids_breadth_first_sorted_siblings() -> None:
    kinds: dict[str, Kind] = {
        "drawn-character": "format_class",
        "wojak": "character",
        "doomer": "character",
        "doomer-girl": "character",
        "yes-chad": "character",
    }
    family = graph.family_ids(WOJAK_LINKS, kinds, "wojak")
    assert family == ["wojak", "doomer", "yes-chad", "doomer-girl"]


def test_family_ids_format_class_node_returns_self_and_direct_children() -> None:
    kinds: dict[str, Kind] = {"drawn-character": "format_class", "wojak": "character"}
    family = graph.family_ids(WOJAK_LINKS, kinds, "drawn-character")
    assert family == ["drawn-character", "wojak"]


def test_family_ids_includes_selected_template_connected_by_character_axis() -> None:
    links = [
        link("doge", "reaction-image"),
        link("cheems", "doge"),
        link("swole-doge", "doge"),
        link("walter", "doge"),
        link("swole-doge-vs-cheems", "swole-doge"),
    ]
    kinds: dict[str, Kind] = {
        "reaction-image": "format_class",
        "doge": "character",
        "cheems": "character",
        "swole-doge": "character",
        "walter": "character",
        "swole-doge-vs-cheems": "template",
    }
    family = graph.family_ids(links, kinds, "swole-doge-vs-cheems")
    assert "swole-doge-vs-cheems" in family
    assert family[0] == "doge"


def test_common_ancestor_finds_shared_wojak() -> None:
    result = graph.common_ancestor(WOJAK_LINKS, "doomer-girl", "yes-chad", "character")
    assert result is not None
    assert result.ancestor_id == "wojak"
    assert result.path_a == ["doomer-girl", "doomer", "wojak"]
    assert result.path_b == ["yes-chad", "wojak"]


def test_common_ancestor_same_node_gives_single_element_paths() -> None:
    result = graph.common_ancestor(WOJAK_LINKS, "doomer", "doomer", "character")
    assert result == graph.common_ancestor(WOJAK_LINKS, "doomer", "doomer", "character")
    assert result is not None
    assert result.ancestor_id == "doomer"
    assert result.path_a == ["doomer"]
    assert result.path_b == ["doomer"]


def test_common_ancestor_none_when_disjoint() -> None:
    links = [link("a", "root1"), link("b", "root2")]
    assert graph.common_ancestor(links, "a", "b", "character") is None


def test_creates_cycle_for_self_parent() -> None:
    assert graph.creates_cycle(WOJAK_LINKS, "wojak", "wojak", "character") is True


def test_creates_cycle_detects_would_be_loop() -> None:
    # doomer's ancestor chain already includes wojak; wojak -> doomer would loop.
    assert graph.creates_cycle(WOJAK_LINKS, "wojak", "doomer", "character") is True


def test_creates_cycle_false_for_safe_new_link() -> None:
    assert graph.creates_cycle(WOJAK_LINKS, "yes-chad", "doomer-girl", "character") is False


def test_parent_is_younger_same_precision_violation() -> None:
    child = node("child", first_seen="2020-01-01", precision="year")
    parent = node("parent", first_seen="2021-01-01", precision="year")
    assert graph.parent_is_younger(child, parent) is True


def test_parent_is_younger_mixed_precision_compares_at_coarser() -> None:
    child = node("child", first_seen="2020-05-01", precision="month")
    parent = node("parent", first_seen="2020-04-15", precision="day")
    assert graph.parent_is_younger(child, parent) is False


def test_parent_is_younger_mixed_precision_detects_violation() -> None:
    child = node("child", first_seen="2020-05-05", precision="day")
    parent = node("parent", first_seen="2021-01-01", precision="year")
    assert graph.parent_is_younger(child, parent) is True


def test_parent_is_younger_unknown_dates_never_violate() -> None:
    child = node("child")
    parent = node("parent", first_seen="2021-01-01", precision="year")
    assert graph.parent_is_younger(child, parent) is False


def test_parent_is_younger_format_class_parent_never_violates() -> None:
    child = node("child", first_seen="2010-01-01", precision="year")
    parent = node("parent", kind="format_class", first_seen="2026-01-01", precision="year")
    assert graph.parent_is_younger(child, parent) is False


def test_related_sentence_both_axes() -> None:
    a = node("doomer", first_seen="2018-03-01", precision="month")
    b = node("yes-chad", first_seen="2018-11-01", precision="month")
    character = node("wojak", first_seen="2010-06-01", precision="month")
    fmt = node("virgin-vs-chad", kind="template", first_seen="2018-08-01", precision="month")
    sentence = graph.related_sentence(a, b, character, fmt)
    assert sentence == (
        "By character: both descend from Wojak (2010). By format: both use Virgin Vs Chad (2018)."
    )


def test_related_sentence_character_only() -> None:
    a = node("doomer", first_seen="2018-03-01", precision="month")
    b = node("yes-chad", first_seen="2018-11-01", precision="month")
    character = node("wojak", first_seen="2010-06-01", precision="month")
    assert graph.related_sentence(a, b, character, None) == (
        "By character: both descend from Wojak (2010)."
    )


def test_related_sentence_ancestor_is_one_of_the_two() -> None:
    doomer = node("doomer", first_seen="2018-03-01", precision="month")
    doomer_girl = node("doomer-girl", first_seen="2019-06-01", precision="month")
    assert graph.related_sentence(doomer_girl, doomer, doomer, None) == (
        "Doomer Girl descends from Doomer (2018)."
    )


def test_related_sentence_character_ancestor_is_format_class_root() -> None:
    a = node("swole-doge-vs-cheems", kind="template")
    b = node("yes-chad")
    root = node("drawn-character", kind="format_class")
    assert graph.related_sentence(a, b, root, None) == "Both are drawn characters."


def test_related_sentence_no_shared_ancestor() -> None:
    a = node("swole-doge-vs-cheems", kind="template")
    b = node("yes-chad")
    assert graph.related_sentence(a, b, None, None) == "No shared ancestor on either line."


def test_lineage_prefers_the_character_parent() -> None:
    links = [
        link("sdvc", "swole-doge"),
        link("sdvc", "virgin-vs-chad", "format"),
        link("swole-doge", "doge"),
        link("doge", "image-macro"),
    ]
    assert graph.lineage(links, "sdvc") == ["sdvc", "swole-doge", "doge", "image-macro"]


def test_lineage_falls_through_to_the_format_parent() -> None:
    links = [
        link("awesome-penguin", "awkward-penguin"),
        link("awkward-penguin", "advice-dog", "format"),
        link("advice-dog", "image-macro", "format"),
    ]
    assert graph.lineage(links, "awesome-penguin") == [
        "awesome-penguin",
        "awkward-penguin",
        "advice-dog",
        "image-macro",
    ]
    assert graph.descent(links, "awesome-penguin", "character") == [
        "awesome-penguin",
        "awkward-penguin",
    ]


def test_lineage_of_an_orphan_and_of_a_cycle() -> None:
    assert graph.lineage([], "orphan") == ["orphan"]
    looped = [link("a", "b"), link("b", "a", "format")]
    assert graph.lineage(looped, "a") == ["a", "b"]
