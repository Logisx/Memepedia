"""The seed script's alias merge: never lose an alias the resolver learned in production."""

from __future__ import annotations

from scripts.seed import _merge_aliases


def test_merge_aliases_keeps_a_new_seed_alias() -> None:
    assert _merge_aliases(["Grogu"], [], "Baby Yoda") == ["Grogu"]


def test_merge_aliases_keeps_a_learned_alias_not_in_the_seed() -> None:
    assert _merge_aliases(["Grogu"], ["The Mandalorian's Kid"], "Baby Yoda") == [
        "Grogu",
        "The Mandalorian's Kid",
    ]


def test_merge_aliases_deduplicates_case_insensitively() -> None:
    assert _merge_aliases(["Grogu"], ["grogu", "GROGU"], "Baby Yoda") == ["Grogu"]


def test_merge_aliases_drops_an_alias_equal_to_the_name() -> None:
    assert _merge_aliases(["Baby Yoda"], [], "Baby Yoda") == []
    assert _merge_aliases([], ["baby yoda"], "Baby Yoda") == []


def test_merge_aliases_drops_a_retired_generic_alias_learned_before_the_seed_change() -> None:
    assert _merge_aliases(["Grogu"], ["The Child"], "Baby Yoda") == ["Grogu"]


def test_merge_aliases_preserves_seed_order_first() -> None:
    merged = _merge_aliases(["Grogu", "Baby Yoda Soup"], ["Old Alias"], "Baby Yoda")
    assert merged == ["Grogu", "Baby Yoda Soup", "Old Alias"]
