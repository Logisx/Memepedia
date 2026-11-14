"""No-network tests for memepedia.verify: text cleaning, sentence splitting, and evidence lookup."""

from __future__ import annotations

from typing import Any

import pytest

from memepedia import contextdev, llm, verify
from memepedia.contextdev import ContextDevError, SearchHit
from memepedia.llm import LLMError
from memepedia.models import Kind, MemeNode

MESSY_MARKDOWN = """---
title: Doomer explainer
date: 2020-01-01
---

# The Evolution of Doomer

Doomer is a drawn character, directly descended from Wojak, who represents a disillusioned young
man. ![a doomer image](https://example.com/doomer.png)

See also [the Wojak article](https://example.com/wojak) for background, e.g. its earliest posts.

| Name | Year |
| --- | --- |
| Wojak | 2010 |
| Doomer | 2018 |

Swole Doge vs. Cheems is a different, unrelated format entirely, built around a two-panel
comparison, not a drawn character at all.
"""


def test_clean_text_drops_front_matter_images_and_table_pipes() -> None:
    cleaned = verify.clean_text(MESSY_MARKDOWN)
    assert "title: Doomer explainer" not in cleaned
    assert "![" not in cleaned
    assert "|" not in cleaned
    assert "#" not in cleaned


def test_clean_text_keeps_link_text_but_not_target() -> None:
    cleaned = verify.clean_text(MESSY_MARKDOWN)
    assert "the Wojak article" in cleaned
    assert "example.com/wojak" not in cleaned


def test_clean_text_drops_meme_com_style_footnote_link() -> None:
    markdown = (
        "First posted to 4chan's /biz/ board in September 2018"
        "[3](https://meme.com/memes/x#ref-3), the character quickly spread."
    )
    cleaned = verify.clean_text(markdown)
    assert "September 2018, the character" in cleaned
    assert "20183" not in cleaned


def test_clean_text_drops_footnote_link_at_end_of_sentence() -> None:
    markdown = (
        "that took hold on 4chan's /biz/ board in mid-2017[2](https://meme.com/memes/x#ref-2)."
    )
    cleaned = verify.clean_text(markdown)
    assert cleaned.strip() == "that took hold on 4chan's /biz/ board in mid-2017."
    assert "20172" not in cleaned


def test_clean_text_drops_wikipedia_style_footnote_link() -> None:
    markdown = (
        "a stereotypical Generation Z teenager or young adult"
        "[\\[3\\]](https://en.wikipedia.org/wiki/X#cite_note-3)."
    )
    cleaned = verify.clean_text(markdown)
    assert cleaned.strip() == "a stereotypical Generation Z teenager or young adult."


def test_clean_text_keeps_non_footnote_numeric_link() -> None:
    markdown = "Read the comments. [0](https://memepulse.net/meme/rage-comics#comments)"
    cleaned = verify.clean_text(markdown)
    assert "0" in cleaned


def test_clean_text_preserves_legitimate_glued_digits() -> None:
    markdown = (
        "Posted on 4chan in 2018, the meme spread via Web3 forums, MP3 rips, "
        "Covid19 jokes, and a 9gag repost."
    )
    cleaned = verify.clean_text(markdown)
    assert cleaned.strip() == markdown


def test_split_sentences_does_not_glue_heading_to_next_paragraph() -> None:
    cleaned = verify.clean_text(MESSY_MARKDOWN)
    sentences = verify.split_sentences(cleaned)
    assert not any(s.startswith("The Evolution of Doomer") and "Wojak" in s for s in sentences)


def test_split_sentences_keeps_abbreviations_intact() -> None:
    text = (
        "Swole Doge vs. Cheems is a two-panel comparison format used across many communities. "
        "It first appeared around 2018, e.g. on several forums and image boards that year."
    )
    sentences = verify.split_sentences(text)
    assert any(s.startswith("Swole Doge vs. Cheems") for s in sentences)
    assert not any(s.strip() == "Swole Doge vs." for s in sentences)


def test_split_sentences_are_verbatim_substrings() -> None:
    cleaned = verify.clean_text(MESSY_MARKDOWN)
    for sentence in verify.split_sentences(cleaned):
        assert sentence in cleaned


def test_split_sentences_filters_by_length() -> None:
    text = "Short. " + ("A" * 500) + ". " + "This one is a reasonable sentence length for a quote."
    sentences = verify.split_sentences(text)
    assert all(40 <= len(s) <= 400 for s in sentences)


def test_mentions_is_case_insensitive_whole_word() -> None:
    assert verify.mentions("doomer is a wojak variant", ["Doomer"])
    assert not verify.mentions("doomerism is a trend", ["Doomer"])


def test_mentions_matches_multi_word_name_with_punctuation() -> None:
    sentence = "Swole Doge vs. Cheems uses the Virgin vs. Chad layout."
    assert verify.mentions(sentence, ["Swole Doge vs. Cheems"])


def test_candidate_sentences_requires_both_names_for_normal_parent() -> None:
    cleaned = verify.clean_text(MESSY_MARKDOWN)
    candidates = verify.candidate_sentences(cleaned, ["Doomer"], ["Wojak"], limit=4)
    assert candidates
    assert all(verify.mentions(s, ["Doomer"]) and verify.mentions(s, ["Wojak"]) for s in candidates)


def test_candidate_sentences_ranks_by_root_overlap_when_parent_is_root() -> None:
    cleaned = verify.clean_text(MESSY_MARKDOWN)
    candidates = verify.candidate_sentences(
        cleaned, ["Doomer"], None, limit=4, root_words=["drawn", "character"]
    )
    assert candidates
    assert "drawn character" in candidates[0]


def _node(
    name: str,
    kind: Kind = "character",
    summary: str | None = None,
    aliases: list[str] | None = None,
) -> MemeNode:
    return MemeNode(
        id=name.lower().replace(" ", "-"),
        name=name,
        aliases=aliases or [],
        kind=kind,
        latin_name=None,
        image_url=None,
        image_credit_url=None,
        first_seen=None,
        date_precision=None,
        summary=summary,
        status="established",
        sightings_24h=0,
        sightings_7d=0,
        nsfw=None,
    )


def test_claim_character_axis() -> None:
    child, parent = _node("Doomer"), _node("Wojak")
    expected = "Doomer is a variant of, or derives from, Wojak."
    assert verify.claim(child, parent, "character") == expected


def test_claim_format_axis() -> None:
    child = _node("Swole Doge vs. Cheems", kind="template")
    parent = _node("Virgin vs. Chad", kind="template")
    result = verify.claim(child, parent, "format")
    assert "uses or derives from the Virgin vs. Chad format" in result


def test_claim_root_parent() -> None:
    child = _node("Wojak")
    root = _node("Drawn character", kind="format_class", summary="A hand-drawn recurring figure.")
    expected = "Wojak is a drawn character: A hand-drawn recurring figure."
    assert verify.claim(child, root, "character") == expected


def test_evidence_in_page_rejects_knowyourmeme_url() -> None:
    child, parent = _node("Doomer"), _node("Wojak")
    result = verify.evidence_in_page(
        child,
        parent,
        "character",
        markdown="Doomer is a Wojak variant, loved by many.",
        url="https://knowyourmeme.com/memes/doomer",
        title="Doomer",
    )
    assert result is None


def test_evidence_in_page_returns_none_when_no_candidates() -> None:
    child, parent = _node("Doomer"), _node("Wojak")
    result = verify.evidence_in_page(
        child,
        parent,
        "character",
        markdown="Nothing relevant here at all, just filler words.",
        url="https://example.com/x",
        title="x",
    )
    assert result is None


def test_evidence_in_page_asserts_verbatim_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "pick_quote", lambda claim, sentences: 0)
    child, parent = _node("Doomer"), _node("Wojak")
    markdown = "Doomer is a drawn character, directly descended from Wojak, a disillusioned figure."
    result = verify.evidence_in_page(
        child, parent, "character", markdown=markdown, url="https://example.com/x", title="X"
    )
    assert result is not None
    assert result.quote in verify.clean_text(markdown)
    assert result.source_url == "https://example.com/x"


def test_evidence_in_page_index_out_of_range_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "pick_quote", lambda claim, sentences: None)
    child, parent = _node("Doomer"), _node("Wojak")
    markdown = "Doomer is a drawn character, directly descended from Wojak, a disillusioned figure."
    result = verify.evidence_in_page(
        child, parent, "character", markdown=markdown, url="https://example.com/x", title="X"
    )
    assert result is None


def test_find_evidence_rejects_knowyourmeme_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(query: str, **kw: Any) -> list[SearchHit]:
        return [
            SearchHit(
                url="https://knowyourmeme.com/memes/doomer",
                title="KYM",
                markdown="Doomer is a Wojak.",
            )
        ]

    monkeypatch.setattr(contextdev, "search", fake_search)
    child, parent = _node("Doomer"), _node("Wojak")
    assert verify.find_evidence(child, parent, "character") is None


def test_find_evidence_search_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(*a: Any, **kw: Any) -> list[SearchHit]:
        raise ContextDevError("boom")

    monkeypatch.setattr(contextdev, "search", fake_search)
    child, parent = _node("Doomer"), _node("Wojak")
    assert verify.find_evidence(child, parent, "character") is None


def test_find_evidence_llm_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search(query: str, **kw: Any) -> list[SearchHit]:
        markdown = "Doomer is a drawn character, directly descended from Wojak, a tired figure."
        return [SearchHit(url="https://example.com/a", title="A", markdown=markdown)]

    def fake_pick_quote(claim: str, sentences: list[str]) -> int:
        raise LLMError("boom")

    monkeypatch.setattr(contextdev, "search", fake_search)
    monkeypatch.setattr(llm, "pick_quote", fake_pick_quote)
    child, parent = _node("Doomer"), _node("Wojak")
    assert verify.find_evidence(child, parent, "character") is None


def test_find_evidence_picks_quote_and_retries_unquoted_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_search(query: str, **kw: Any) -> list[SearchHit]:
        calls.append(query)
        if len(calls) == 1:
            return [SearchHit(url="https://example.com/a", title="A", markdown="Nothing useful.")]
        markdown = "Doomer is a drawn character, directly descended from Wojak, a tired figure."
        return [SearchHit(url="https://example.com/b", title="B", markdown=markdown)]

    monkeypatch.setattr(contextdev, "search", fake_search)
    monkeypatch.setattr(llm, "pick_quote", lambda claim, sentences: 0)
    child, parent = _node("Doomer"), _node("Wojak")
    evidence = verify.find_evidence(child, parent, "character")
    assert len(calls) == 2
    assert evidence is not None
    assert evidence.source_url == "https://example.com/b"
