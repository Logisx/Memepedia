"""Unit tests for the pure parsing functions in the web-data layer. No network."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

import pytest

from memepedia import contextdev
from memepedia.sources import FEEDS, imgflip, lemmy, reddit

DATA = Path(__file__).parent / "data"


def _load_json(name: str) -> dict:
    return json.loads((DATA / name).read_text())


def test_lemmy_parse_posts_keeps_only_clean_image_posts() -> None:
    posts = lemmy.parse_posts(_load_json("lemmy_memes.json"), source="lemmy:test")

    assert [p.post_url for p in posts] == [
        "https://lemmy.ca/post/73835763",
        "https://lemmy.ca/post/73835662",
    ]
    first = posts[0]
    assert first.platform == "lemmy"
    assert first.source == "lemmy:test"
    assert first.title == "Spell it out"
    assert first.author == "Quilotoa"
    assert first.image_url == "https://lemmy.ca/pictrs/image/ecf653f9.png"
    assert first.posted_at.tzinfo is not None


def test_lemmy_parse_posts_skips_pinned_posts() -> None:
    posts = lemmy.parse_posts(_load_json("lemmy_memes.json"), source="lemmy:test")

    assert "https://lemmy.world/post/6" not in [p.post_url for p in posts]


def test_reddit_parse_atom_prefers_full_image_and_skips_text_posts() -> None:
    xml_text = (DATA / "reddit_new.xml").read_text()
    posts = reddit.parse_atom(xml_text, source="reddit:test")

    assert len(posts) == 2
    first = posts[0]
    assert first.image_url == "https://i.redd.it/8pzlu3vlwk1i1.png"
    assert first.post_url == "https://www.reddit.com/r/memes/comments/1xw28dp/the_sheer_idea/"
    assert first.author == "thought_cream84"
    assert first.title == "The sheer idea made me so enthusiastic"
    assert first.posted_at.tzinfo is not None


def test_reddit_parse_atom_raises_on_garbage_input() -> None:
    try:
        reddit.parse_atom("not xml at all", source="reddit:test")
    except Exception as exc:  # noqa: BLE001
        assert "unparsable" in str(exc)
    else:
        raise AssertionError("expected a SourceError")


def test_imgflip_parse_stream_joins_images_to_links_and_skips_gifs() -> None:
    html = (DATA / "imgflip_stream.html").read_text()
    images = json.loads((DATA / "imgflip_images.json").read_text())
    result = contextdev.ScrapeResult(
        url="https://imgflip.com/m/fun?sort=latest",
        title=None,
        markdown=None,
        html=html,
        images=images,
        credits=1.0,
    )
    posts = imgflip.parse_stream(result, source="imgflip:test")

    assert [p.post_url for p in posts] == [
        "https://imgflip.com/i/b5ve9r",
        "https://imgflip.com/i/b5vdvm",
    ]
    assert posts[0].title == "I'll allow it | caption text"
    assert posts[1].title == "Everyone Should Stop | some caption"


def test_search_hits_parsing() -> None:
    hits = contextdev.parse_search_hits(_load_json("search_response.json"))

    assert len(hits) == 2
    assert hits[0].url == "https://howtodothingswithmemes.substack.com/p/doomer"
    assert hits[0].title == "The Evolution of Doomer"
    assert hits[0].markdown is not None
    assert "Doomer" in hits[0].markdown
    assert hits[1].markdown is None


def test_scrape_sends_max_age_ms_only_when_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Context.dev caches a scrape for 3 days by default; a feed fetch must opt out of that."""
    bodies: list[dict[str, Any]] = []

    class _Resp:
        status_code = 200
        is_success = True
        headers: dict[str, str] = {}

        def json(self) -> dict[str, Any]:
            return {"markdown": {"data": "x"}}

    def fake_request(
        method: str, path: str, *, json_body: dict[str, Any] | None, timeout: float
    ) -> _Resp:
        assert json_body is not None
        bodies.append(json_body)
        return _Resp()

    monkeypatch.setattr(contextdev, "_request", fake_request)
    monkeypatch.setattr(contextdev, "_guard", lambda what: None)
    monkeypatch.setattr(contextdev.config, "DATA_DIR", tmp_path)

    contextdev.scrape("https://example.org", formats={"markdown": True}, label="t")
    contextdev.scrape("https://example.org", formats={"markdown": True}, label="t", max_age_ms=0)

    assert "maxAgeMs" not in bodies[0]
    assert bodies[1]["maxAgeMs"] == 0


def test_reddit_and_imgflip_fetches_force_a_fresh_scrape(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both feed fetchers must bypass Context.dev's (three-day-default) cache on every poll."""
    calls: list[int | None] = []

    def fake_scrape(
        url: str,
        *,
        formats: dict[str, Any],
        label: str,
        max_age_ms: int | None = None,
        timeout: float = 60.0,
    ) -> contextdev.ScrapeResult:
        calls.append(max_age_ms)
        return contextdev.ScrapeResult(
            url=url, title=None, markdown="", html="", images=[], credits=0.0
        )

    monkeypatch.setattr(contextdev, "scrape", fake_scrape)
    feed = next(f for f in FEEDS if f.platform == "reddit")
    imgflip_feed = next(f for f in FEEDS if f.platform == "imgflip")

    # empty fake markdown/html raises SourceError; only that the call was made matters here
    with contextlib.suppress(Exception):
        reddit.fetch_raw(feed)
    imgflip.fetch_raw(imgflip_feed)

    assert calls == [0, 0]


def test_blocked_detection() -> None:
    blocked_body = _load_json("scrape_blocked.json")
    message = contextdev.blocked_message(blocked_body)

    assert message is not None
    assert "anti-bot" in message

    clean_body = {"markdown": {"requested": True, "success": True, "data": "hello"}}
    assert contextdev.blocked_message(clean_body) is None
