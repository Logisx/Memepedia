"""No-network tests for the pure parsing/validation parts of memepedia.llm."""

from __future__ import annotations

import pytest

from memepedia import llm
from memepedia.llm import (
    LLMBlockedError,
    RootInfo,
    _clamp_quote_index,
    _parse_clusters,
    _parse_draft_chain,
    _parse_same_or_new,
    _parse_vision_label,
)

ROOTS = [
    RootInfo(id="drawn-character", name="Drawn Character", summary="Hand-drawn recurring figure."),
    RootInfo(id="image-macro", name="Image Macro", summary="Captioned photo."),
]


def test_generate_timeout_gives_a_realistic_deadline() -> None:
    """One retry at the old 20s budget raced a ~40s observed live failure; 60s per attempt
    gives a complex draft call a real chance to finish before Gemini's own deadline hits."""
    assert llm._TIMEOUT_MS == 60_000


def test_parse_vision_label_clamps_confidence_above_one() -> None:
    raw = {
        "is_meme": True,
        "template_guess": "Doomer",
        "confidence": 1.7,
        "structure_class": "drawn-character",
        "subjects": ["doomer"],
        "overlaid_text": None,
        "catchphrase": None,
        "description": "a tired drawn figure",
    }
    label = _parse_vision_label(raw, ROOTS)
    assert label.confidence == 1.0


def test_parse_vision_label_clamps_confidence_below_zero() -> None:
    raw = {
        "is_meme": True,
        "template_guess": None,
        "confidence": -0.3,
        "structure_class": None,
        "subjects": [],
        "overlaid_text": None,
        "catchphrase": None,
        "description": "x",
    }
    label = _parse_vision_label(raw, ROOTS)
    assert label.confidence == 0.0


def test_parse_vision_label_rejects_unknown_structure_class() -> None:
    raw = {
        "is_meme": True,
        "template_guess": "Doomer",
        "confidence": 0.9,
        "structure_class": "not-a-real-root",
        "subjects": [],
        "overlaid_text": None,
        "catchphrase": None,
        "description": "x",
    }
    label = _parse_vision_label(raw, ROOTS)
    assert label.structure_class is None


def test_parse_vision_label_keeps_known_structure_class() -> None:
    raw = {
        "is_meme": True,
        "template_guess": None,
        "confidence": 0.5,
        "structure_class": "image-macro",
        "subjects": [],
        "overlaid_text": None,
        "catchphrase": None,
        "description": "x",
    }
    label = _parse_vision_label(raw, ROOTS)
    assert label.structure_class == "image-macro"


def test_parse_vision_label_defaults_nsfw_false_when_missing() -> None:
    raw = {
        "is_meme": True,
        "template_guess": "Doomer",
        "confidence": 0.9,
        "structure_class": None,
        "subjects": [],
        "overlaid_text": None,
        "catchphrase": None,
        "description": "x",
    }
    label = _parse_vision_label(raw, ROOTS)
    assert label.nsfw is False
    assert label.nsfw_reason is None


def test_parse_vision_label_reads_nsfw_true_with_reason() -> None:
    raw = {
        "is_meme": True,
        "template_guess": None,
        "confidence": 0.2,
        "structure_class": None,
        "subjects": [],
        "overlaid_text": None,
        "catchphrase": None,
        "description": "x",
        "nsfw": True,
        "nsfw_reason": "graphic injury",
    }
    label = _parse_vision_label(raw, ROOTS)
    assert label.nsfw is True
    assert label.nsfw_reason == "graphic injury"


def test_vision_label_treats_a_safety_block_as_nsfw(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: object, **kwargs: object) -> str:
        raise LLMBlockedError("Gemini returned no text (likely blocked by safety filters)")

    monkeypatch.setattr(llm, "_generate", blocked)
    label = llm.vision_label(b"bytes", "image/png", title=None, roots=ROOTS)
    assert label.nsfw is True
    assert label.nsfw_reason is not None
    assert label.is_meme is False
    assert label.template_guess is None


def test_label_nsfw_only_treats_a_safety_block_as_nsfw(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: object, **kwargs: object) -> str:
        raise LLMBlockedError("Gemini returned no text (likely blocked by safety filters)")

    monkeypatch.setattr(llm, "_generate", blocked)
    nsfw, reason = llm.label_nsfw_only(b"bytes", "image/png")
    assert nsfw is True
    assert reason is not None


def test_parse_draft_chain_drops_links_with_unknown_names() -> None:
    raw = {
        "subject": "Doomer",
        "known": True,
        "nodes": [
            {
                "existing_id": None,
                "name": "Doomer",
                "aliases": [],
                "kind": "character",
                "first_seen": "2018-01-01",
                "date_precision": "year",
                "summary": "A tired figure.",
                "latin_name": "Wojakus desperatus",
            },
            {
                "existing_id": "drawn-character",
                "name": "Drawn Character",
                "aliases": [],
                "kind": "format_class",
                "first_seen": None,
                "date_precision": None,
                "summary": None,
                "latin_name": None,
            },
        ],
        "links": [
            {"child": "Doomer", "parent": "Drawn Character", "axis": "character"},
            {"child": "Doomer", "parent": "Wojak", "axis": "character"},
        ],
    }
    chain = _parse_draft_chain(raw)
    assert len(chain.nodes) == 2
    assert len(chain.links) == 1
    assert chain.links[0].parent == "Drawn Character"


def test_parse_draft_chain_keeps_valid_links() -> None:
    raw = {
        "subject": "X",
        "known": False,
        "nodes": [
            {
                "existing_id": None,
                "name": "A",
                "aliases": [],
                "kind": "template",
                "first_seen": None,
                "date_precision": None,
                "summary": None,
                "latin_name": None,
            },
            {
                "existing_id": None,
                "name": "B",
                "aliases": [],
                "kind": "template",
                "first_seen": None,
                "date_precision": None,
                "summary": None,
                "latin_name": None,
            },
        ],
        "links": [{"child": "A", "parent": "B", "axis": "format"}],
    }
    chain = _parse_draft_chain(raw)
    assert len(chain.links) == 1


def test_parse_same_or_new_returns_known_id() -> None:
    assert _parse_same_or_new({"same_as_id": "doomer"}, {"doomer", "bloomer"}) == "doomer"


def test_parse_same_or_new_rejects_unknown_id() -> None:
    assert _parse_same_or_new({"same_as_id": "not-a-candidate"}, {"doomer"}) is None


def test_parse_same_or_new_passes_through_none() -> None:
    assert _parse_same_or_new({"same_as_id": None}, {"doomer"}) is None


def test_clamp_quote_index_in_bounds() -> None:
    assert _clamp_quote_index(2, 5) == 2


def test_clamp_quote_index_negative_rejected() -> None:
    assert _clamp_quote_index(-1, 5) is None


def test_clamp_quote_index_too_large_rejected() -> None:
    assert _clamp_quote_index(5, 5) is None


def test_clamp_quote_index_none_passes_through() -> None:
    assert _clamp_quote_index(None, 5) is None


def test_clamp_quote_index_rejects_non_int() -> None:
    assert _clamp_quote_index("2", 5) is None
    assert _clamp_quote_index(True, 5) is None


def test_parse_clusters_drops_unknown_sighting_ids() -> None:
    raw = {
        "clusters": [
            {
                "name": "New Format",
                "kind": "template",
                "structure_class": None,
                "summary": "A new recurring joke.",
                "latin_name": "Novus formatus",
                "shared": "structure",
                "sighting_ids": ["s1", "s2", "unknown-id"],
            }
        ]
    }
    clusters = _parse_clusters(raw, {"s1", "s2", "s3"})
    assert len(clusters) == 1
    assert clusters[0].sighting_ids == ("s1", "s2")


def test_parse_clusters_drops_empty_clusters() -> None:
    raw = {
        "clusters": [
            {
                "name": "Nothing Real",
                "kind": "template",
                "structure_class": None,
                "summary": "x",
                "latin_name": None,
                "shared": "image",
                "sighting_ids": ["unknown-only"],
            }
        ]
    }
    assert _parse_clusters(raw, {"s1"}) == []
