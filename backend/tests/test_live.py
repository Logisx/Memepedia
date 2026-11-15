"""The live loop: classify/qualifies rules, one tick end to end, specimen detection, the rest."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from memepedia import db, live, llm, resolver, sources, store, trace
from memepedia.config import Settings
from memepedia.models import MemeNode, Post, VisionLabel


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = dict(
        database_url=None,
        local_db_name="memepedia_test",
        contextdev_key=None,
        gemini_key=None,
        gemini_model="test-model",
        public_base_url=None,
        vision_per_tick=10,
        vision_min_confidence=0.7,
        auto_traces_per_tick=1,
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _no_guardrail_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test here may reach the real guardrail model: by default it "fails", so the labeller's
    own nsfw verdict stands. Tests about the guardrail patch `llm.label_nsfw_only` themselves."""

    def unavailable(image: bytes, mime_type: str) -> tuple[bool, str | None]:
        raise llm.LLMUnavailable("guardrail stubbed out in tests")

    monkeypatch.setattr(llm, "label_nsfw_only", unavailable)


def _label(**overrides: object) -> VisionLabel:
    base: dict[str, object] = dict(
        is_meme=True,
        template_guess="Doomer",
        confidence=0.9,
        structure_class=None,
        subjects=[],
        overlaid_text=None,
        catchphrase=None,
        description="a tired-looking figure",
        nsfw=False,
        nsfw_reason=None,
    )
    base.update(overrides)
    return VisionLabel(**base)


def _post(url: str, *, posted_at: datetime, author: str | None = "a") -> Post:
    return Post(
        platform="lemmy",
        source="test",
        post_url=url,
        image_url=url + ".img",
        title="t",
        author=author,
        posted_at=posted_at,
    )


def _member(sid: str, author: str | None, image: str, text: str | None) -> live.Member:
    return live.Member(sid, author, image, text)


# --- classify -----------------------------------------------------------------------------


_INDEX = [
    ("Doomer", "doomer"),
    ("Wojak", "wojak"),
    ("Pepe the Frog", "pepe"),
    ("Drake Hotline Bling", "drake"),
    ("Haggis", "haggis"),
]
_KINDS = {
    "doomer": "character",
    "wojak": "character",
    "pepe": "character",
    "drake": "template",
    "haggis": "character",
}
_T = live.Thresholds(exact=0.7, near=0.85, subjects=True)


def _matcher() -> resolver.Matcher:
    return resolver.Matcher(_INDEX, _KINDS, allow_llm=False)


def _stub_resolution(monkeypatch: pytest.MonkeyPatch, answer: Callable[[str], str | None]) -> None:
    """Replaces the near-match step so no test reaches the real LLM; exact matches still work."""
    monkeypatch.setattr(resolver, "_resolve_in", lambda index, name, hint, allow_llm: answer(name))


def _near_calls(monkeypatch: pytest.MonkeyPatch, answer: str | None = None) -> list[str]:
    """Replaces the near-match step; returns the guesses that were put to it."""
    asked: list[str] = []

    def fake(index: object, name: str, hint: str | None, allow_llm: bool) -> str | None:
        asked.append(name)
        return answer

    monkeypatch.setattr(resolver, "_resolve_in", fake)
    return asked


def test_classify_not_a_meme_is_unclassified(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _near_calls(monkeypatch, "doomer")
    label = _label(is_meme=False, subjects=["Wojak"])
    assert live.classify(label, _T, _matcher()) == (None, "unclassified")
    assert asked == []


def test_classify_exact_guess_resolves_between_the_two_thresholds() -> None:
    label = _label(template_guess="Doomer", confidence=0.75)
    assert live.classify(label, _T, _matcher()) == ("doomer", "resolved")


def test_classify_exact_guess_below_the_exact_threshold_stays_pending() -> None:
    label = _label(template_guess="Doomer", confidence=0.6)
    assert live.classify(label, _T, _matcher()) == (None, "pending")


def test_classify_boundary_confidence_counts_as_confident() -> None:
    label = _label(template_guess="Doomer", confidence=0.7)
    assert live.classify(label, _T, _matcher()) == ("doomer", "resolved")


def test_classify_near_guess_needs_the_higher_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _near_calls(monkeypatch, "doomer")
    label = _label(template_guess="Doomer Boy", confidence=0.75)
    assert live.classify(label, _T, _matcher()) == (None, "pending")
    assert asked == []


def test_classify_near_guess_above_the_higher_threshold_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked = _near_calls(monkeypatch, "doomer")
    label = _label(template_guess="Doomer Boy", confidence=0.9)
    assert live.classify(label, _T, _matcher()) == ("doomer", "resolved")
    assert asked == ["Doomer Boy"]


def test_classify_near_guess_without_a_match_stays_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _near_calls(monkeypatch, None)
    label = _label(template_guess="Brand New Thing", confidence=0.95)
    assert live.classify(label, _T, _matcher()) == (None, "pending")


def test_classify_a_depicted_character_resolves_without_a_guess() -> None:
    label = _label(template_guess=None, confidence=0.0, subjects=["a man", "Wojak"])
    assert live.classify(label, _T, _matcher()) == ("wojak", "resolved")


def test_classify_subjects_naming_two_characters_stay_pending() -> None:
    label = _label(template_guess=None, subjects=["Wojak", "Pepe the Frog"])
    assert live.classify(label, _T, _matcher()) == (None, "pending")


def test_classify_a_subject_that_is_a_template_stays_pending() -> None:
    label = _label(template_guess=None, subjects=["Drake Hotline Bling"])
    assert live.classify(label, _T, _matcher()) == (None, "pending")


def test_classify_a_generic_subject_never_stamps() -> None:
    label = _label(template_guess=None, subjects=["Haggis"])
    assert live.classify(label, _T, _matcher()) == (None, "pending")


def test_classify_subjects_can_be_switched_off() -> None:
    label = _label(template_guess=None, subjects=["Wojak"])
    off = live.Thresholds(exact=0.7, near=0.85, subjects=False)
    assert live.classify(label, off, _matcher()) == (None, "pending")


def test_classify_the_guess_wins_over_a_depicted_character() -> None:
    label = _label(template_guess="Doomer", confidence=0.9, subjects=["Pepe the Frog"])
    assert live.match_label(label, _T, _matcher()) == live.LabelMatch("doomer", "exact")


def test_match_label_reports_how_it_matched(monkeypatch: pytest.MonkeyPatch) -> None:
    _near_calls(monkeypatch, "doomer")
    near = _label(template_guess="Doomer Boy", confidence=0.9)
    assert live.match_label(near, _T, _matcher()) == live.LabelMatch("doomer", "near")
    subject = _label(template_guess=None, subjects=["Wojak"])
    assert live.match_label(subject, _T, _matcher()) == live.LabelMatch("wojak", "subject")


# --- qualifies ------------------------------------------------------------------------------


def test_qualifies_too_few_members() -> None:
    members = [_member("1", "a", "img", "t1"), _member("2", "b", "img", "t2")]
    assert live.qualifies(members, "structure") is False


def test_qualifies_one_author_fails() -> None:
    members = [_member(str(i), "same", "img", f"t{i}") for i in range(3)]
    assert live.qualifies(members, "structure") is False


def test_qualifies_identical_text_is_a_repost() -> None:
    members = [_member(str(i), f"a{i}", "img", "same caption") for i in range(3)]
    assert live.qualifies(members, "image") is False


def test_qualifies_structure_with_differing_captions() -> None:
    members = [_member(str(i), f"a{i}", "img", f"t{i}") for i in range(3)]
    assert live.qualifies(members, "structure") is True


def test_qualifies_phrase_inverts_to_the_image_check() -> None:
    same_text_diff_images = [_member(str(i), f"a{i}", f"img{i}", "same phrase") for i in range(3)]
    assert live.qualifies(same_text_diff_images, "phrase") is True
    same_text_same_image = [_member(str(i), f"a{i}", "img", "same phrase") for i in range(3)]
    assert live.qualifies(same_text_same_image, "phrase") is False


def test_qualifies_missing_authors_count_once() -> None:
    mixed = [
        _member("1", None, "i1", "t1"),
        _member("2", None, "i2", "t2"),
        _member("3", "bob", "i3", "t3"),
    ]
    assert live.qualifies(mixed, "structure") is True
    all_anonymous = [_member(str(i), None, f"i{i}", f"t{i}") for i in range(3)]
    assert live.qualifies(all_anonymous, "structure") is False


# --- tick ------------------------------------------------------------------------------------

_FEED_KEY = "lemmy:lemmy.world/memes"


def test_tick_saves_each_state_and_skips_known(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    known_post = _post("https://t.test/tick-known", posted_at=now)
    resolved_post = _post("https://t.test/tick-resolved", posted_at=now)
    pending_post = _post("https://t.test/tick-pending", posted_at=now)
    unclassified_post = _post("https://t.test/tick-unclassified", posted_at=now)
    assert store.insert_sighting(known_post, None, None, "unclassified") is not None

    monkeypatch.setattr(
        sources, "fetch", lambda feed: [known_post, resolved_post, pending_post, unclassified_post]
    )
    monkeypatch.setattr(live, "get_settings", lambda: _settings())

    def fake_download(url: str) -> tuple[bytes, str] | None:
        return None if "unclassified" in url else (b"data-" + url.encode(), "image/png")

    monkeypatch.setattr(live, "_download_image", fake_download)

    def fake_vision_label(
        data: bytes, mime: str, *, title: str | None, roots: object, known_names: object
    ) -> VisionLabel:
        name = "Doomer" if b"tick-resolved" in data else "Brand New Thing"
        return _label(template_guess=name, confidence=0.9)

    monkeypatch.setattr(llm, "vision_label", fake_vision_label)
    _stub_resolution(monkeypatch, lambda name: "doomer" if name == "Doomer" else None)
    monkeypatch.setattr(trace, "run", lambda *a, **kw: None)

    report = live.tick(_FEED_KEY)

    assert report.fetched == 4
    assert report.fresh == 3
    assert report.looked == 3
    assert report.resolved == 1
    assert report.pending == 1
    assert report.unclassified == 1
    assert report.errors == []

    for url in (
        known_post.post_url,
        resolved_post.post_url,
        pending_post.post_url,
        unclassified_post.post_url,
    ):
        db.execute("DELETE FROM sightings WHERE post_url = %s", (url,))


def test_tick_respects_per_tick_cap(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    posts = [
        _post(f"https://t.test/cap-{i}", posted_at=now - timedelta(minutes=i)) for i in range(5)
    ]
    monkeypatch.setattr(sources, "fetch", lambda feed: posts)
    monkeypatch.setattr(
        live, "get_settings", lambda: _settings(vision_per_tick=2, auto_traces_per_tick=0)
    )
    monkeypatch.setattr(live, "_download_image", lambda url: None)

    report = live.tick(_FEED_KEY)

    assert report.fetched == 5
    assert report.fresh == 5
    assert report.looked == 2
    assert report.unclassified == 2

    for post in posts:
        db.execute("DELETE FROM sightings WHERE post_url = %s", (post.post_url,))


def test_tick_survives_a_source_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(feed: object) -> list[Post]:
        raise sources.SourceError("lemmy is down")

    monkeypatch.setattr(sources, "fetch", boom)
    report = live.tick(_FEED_KEY)
    assert report.errors == ["lemmy is down"]
    assert report.fetched == 0


def test_tick_unknown_feed_key_is_an_error() -> None:
    report = live.tick("no-such-feed")
    assert report.fetched == 0
    assert "no-such-feed" in report.errors[0]


def test_tick_vision_failure_is_not_saved(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    post = _post("https://t.test/vision-fail", posted_at=now)
    monkeypatch.setattr(sources, "fetch", lambda feed: [post])
    monkeypatch.setattr(live, "get_settings", lambda: _settings())
    monkeypatch.setattr(live, "_download_image", lambda url: (b"data", "image/png"))

    def boom(*a: object, **kw: object) -> VisionLabel:
        raise llm.LLMError("gemini is unhappy")

    monkeypatch.setattr(llm, "vision_label", boom)

    report = live.tick(_FEED_KEY)

    assert report.looked == 1
    assert (report.resolved, report.pending, report.unclassified) == (0, 0, 0)
    assert any("gemini is unhappy" in e for e in report.errors)
    assert db.fetch_one("SELECT 1 FROM sightings WHERE post_url = %s", (post.post_url,)) is None


def test_tick_auto_trace_attaches_and_respects_cap(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    post_a = _post("https://t.test/autotrace-a", posted_at=now, author="alice")
    post_b = _post("https://t.test/autotrace-b", posted_at=now - timedelta(seconds=1), author="bob")
    monkeypatch.setattr(sources, "fetch", lambda feed: [post_a, post_b])
    monkeypatch.setattr(live, "get_settings", lambda: _settings(auto_traces_per_tick=1))
    monkeypatch.setattr(live, "_download_image", lambda url: (b"data-" + url.encode(), "image/png"))
    monkeypatch.setattr(
        llm,
        "vision_label",
        lambda *a, **kw: _label(template_guess="New Specimen X", confidence=0.95),
    )
    _stub_resolution(monkeypatch, lambda name: None)

    calls: list[tuple[str, bool]] = []

    def fake_trace_run(
        query: str, *, context: str | None = None, as_specimen: bool = False
    ) -> str | None:
        calls.append((query, as_specimen))
        # The trace is what creates the node, so it must not exist before the tick: an existing
        # node of that name would be an exact match and stamp both posts straight away.
        store.upsert_node(
            MemeNode(
                id="new-specimen-node",
                name="New Specimen X",
                aliases=[],
                kind="template",
                latin_name=None,
                image_url=None,
                image_credit_url=None,
                first_seen=None,
                date_precision=None,
                summary=None,
                status="specimen",
                sightings_24h=0,
                sightings_7d=0,
                nsfw=None,
            )
        )
        return "new-specimen-node"

    monkeypatch.setattr(trace, "run", fake_trace_run)

    report = live.tick(_FEED_KEY)

    assert report.pending == 2
    assert calls == [("New Specimen X", True)]
    assert report.traced == ["new-specimen-node"]
    resolved_row = db.fetch_one(
        "SELECT node_id, state FROM sightings WHERE post_url = %s", (post_a.post_url,)
    )
    assert resolved_row == {"node_id": "new-specimen-node", "state": "resolved"}
    other_row = db.fetch_one(
        "SELECT node_id, state FROM sightings WHERE post_url = %s", (post_b.post_url,)
    )
    assert other_row == {"node_id": None, "state": "pending"}

    db.execute(
        "DELETE FROM sightings WHERE post_url = ANY(%s)", ([post_a.post_url, post_b.post_url],)
    )
    db.execute("DELETE FROM nodes WHERE id = %s", ("new-specimen-node",))


def test_tick_auto_trace_single_author_is_not_traced(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One author posting the same guess twice does not count as a second sighting."""
    now = datetime.now(UTC)
    post_a = _post("https://t.test/autotrace-solo-a", posted_at=now, author="solo")
    post_b = _post(
        "https://t.test/autotrace-solo-b", posted_at=now - timedelta(seconds=1), author="solo"
    )
    monkeypatch.setattr(sources, "fetch", lambda feed: [post_a, post_b])
    monkeypatch.setattr(live, "get_settings", lambda: _settings(auto_traces_per_tick=2))
    monkeypatch.setattr(live, "_download_image", lambda url: (b"data-" + url.encode(), "image/png"))
    monkeypatch.setattr(
        llm, "vision_label", lambda *a, **kw: _label(template_guess="Solo Thing", confidence=0.95)
    )
    _stub_resolution(monkeypatch, lambda name: None)

    calls: list[str] = []
    monkeypatch.setattr(trace, "run", lambda *a, **kw: (calls.append(a[0]), None)[1])

    report = live.tick(_FEED_KEY)

    assert report.pending == 2
    assert calls == []
    assert report.traced == []

    db.execute(
        "DELETE FROM sightings WHERE post_url = ANY(%s)", ([post_a.post_url, post_b.post_url],)
    )


def test_has_second_sighting_requires_two_distinct_authors() -> None:
    def row(author: str | None, guess: str) -> dict[str, object]:
        return {"author": author, "vision": {"template_guess": guess}}

    assert live._has_second_sighting("Doomer", [row("a", "Doomer")]) is False
    assert live._has_second_sighting("Doomer", [row("a", "Doomer"), row("a", "Doomer")]) is False
    assert live._has_second_sighting("Doomer", [row("a", "Doomer"), row("b", "Doomer")]) is True
    assert live._has_second_sighting("Doomer", [row(None, "Doomer"), row(None, "Doomer")]) is False
    assert live._has_second_sighting("Doomer", [row(None, "Doomer"), row("a", "Doomer")]) is True


def test_has_second_sighting_normalises_names_and_ignores_other_guesses() -> None:
    def row(author: str | None, guess: str | None) -> dict[str, object]:
        return {"author": author, "vision": {"template_guess": guess}}

    rows = [
        row("a", "The Doomer Meme"),
        row("b", "doomer template"),
        row("c", "unrelated thing"),
        row("d", None),
    ]
    assert live._has_second_sighting("Doomer", rows) is True


def test_auto_trace_uses_the_detect_specimens_window(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, int] = {}

    def fake_pending_sightings(hours: int = 72) -> list[dict[str, object]]:
        seen["hours"] = hours
        return [{"author": "solo", "vision": {"template_guess": "Thing"}}]

    monkeypatch.setattr(store, "pending_sightings", fake_pending_sightings)
    errors: list[str] = []

    traced = live._auto_trace([("sid-1", "Thing")], 1, errors)

    assert traced == []
    assert seen["hours"] == live._PENDING_WINDOW_HOURS


# --- detect_specimens --------------------------------------------------------------------------


def _insert_pending(
    url: str, *, author: str | None, overlaid_text: str, posted_at: datetime
) -> str:
    vision = _label(
        template_guess=None,
        confidence=0.3,
        structure_class="image-macro",
        overlaid_text=overlaid_text,
    )
    post = Post(
        platform="lemmy",
        source="test",
        post_url=url,
        image_url=url + ".img",
        title="t",
        author=author,
        posted_at=posted_at,
    )
    sid = store.insert_sighting(post, vision, None, "pending")
    assert sid is not None
    return sid


def test_detect_specimens_skips_the_llm_when_nothing_changed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live, "_last_pending_ids", None)
    now = datetime.now(UTC)
    ids = [
        _insert_pending(
            f"https://t.test/ds-nochange-{i}", author=f"a{i}", overlaid_text=f"t{i}", posted_at=now
        )
        for i in range(3)
    ]
    calls: list[int] = []

    def fake_cluster_pending(items: Sequence[llm.PendingItem]) -> list[llm.Cluster]:
        calls.append(len(items))
        return []

    monkeypatch.setattr(llm, "cluster_pending", fake_cluster_pending)

    live.detect_specimens()
    assert len(calls) == 1
    live.detect_specimens()
    assert len(calls) == 1

    db.execute("DELETE FROM sightings WHERE post_url LIKE 'https://t.test/ds-nochange-%%'")
    assert ids


def test_detect_specimens_full_flow(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live, "_last_pending_ids", None)
    now = datetime.now(UTC)
    ids_new = [
        _insert_pending(
            f"https://t.test/ds-new-{i}",
            author=f"newauthor{i}",
            overlaid_text=f"caption {i}",
            posted_at=now - timedelta(minutes=i),
        )
        for i in range(3)
    ]
    ids_existing = [
        _insert_pending(
            f"https://t.test/ds-existing-{i}",
            author=f"exauthor{i}",
            overlaid_text=f"c{i}",
            posted_at=now,
        )
        for i in range(3)
    ]

    def fake_cluster(items: object) -> list[llm.Cluster]:
        return [
            llm.Cluster(
                name="Brand New Thing",
                kind="template",
                structure_class="image-macro",
                summary="a new format spreading fast",
                latin_name="Novus memus",
                shared="structure",
                sighting_ids=(*ids_new, "invented-id-999"),
            ),
            llm.Cluster(
                name="Existing Thing",
                kind="template",
                structure_class="image-macro",
                summary="turned out to already be known",
                latin_name=None,
                shared="structure",
                sighting_ids=tuple(ids_existing),
            ),
        ]

    monkeypatch.setattr(llm, "cluster_pending", fake_cluster)
    store.upsert_node(
        MemeNode(
            id="brand-new-specimen",
            name="Brand New Thing",
            aliases=[],
            kind="template",
            latin_name=None,
            image_url=None,
            image_credit_url=None,
            first_seen=None,
            date_precision=None,
            summary=None,
            status="specimen",
            sightings_24h=0,
            sightings_7d=0,
            nsfw=None,
        )
    )
    store.upsert_node(
        MemeNode(
            id="existing-established",
            name="Existing Thing",
            aliases=[],
            kind="template",
            latin_name=None,
            image_url="https://existing.test/img.png",
            image_credit_url="https://existing.test/credit",
            first_seen=None,
            date_precision=None,
            summary=None,
            status="established",
            sightings_24h=0,
            sightings_7d=0,
            nsfw=None,
        )
    )

    def fake_trace_run(
        query: str, *, context: str | None = None, as_specimen: bool = False
    ) -> str | None:
        return "brand-new-specimen" if query == "Brand New Thing" else "existing-established"

    monkeypatch.setattr(trace, "run", fake_trace_run)

    attached = live.detect_specimens()

    assert set(attached) == {"brand-new-specimen", "existing-established"}
    for sid in ids_new:
        row = db.fetch_one("SELECT node_id, state FROM sightings WHERE id = %s", (sid,))
        assert row == {"node_id": "brand-new-specimen", "state": "resolved"}
    for sid in ids_existing:
        row = db.fetch_one("SELECT node_id, state FROM sightings WHERE id = %s", (sid,))
        assert row == {"node_id": "existing-established", "state": "resolved"}

    new_node = store.get_node("brand-new-specimen")
    assert new_node is not None
    assert new_node.image_url is not None
    assert new_node.image_credit_url is not None

    existing_node = store.get_node("existing-established")
    assert existing_node is not None
    assert existing_node.image_url == "https://existing.test/img.png"

    new_history = db.fetch_all("SELECT id FROM history WHERE node_id = %s", ("brand-new-specimen",))
    assert len(new_history) == 1
    existing_history = db.fetch_all(
        "SELECT id FROM history WHERE node_id = %s", ("existing-established",)
    )
    assert existing_history == []

    db.execute("DELETE FROM sightings WHERE post_url LIKE 'https://t.test/ds-%%'")
    db.execute(
        "DELETE FROM history WHERE node_id = ANY(%s)",
        (["brand-new-specimen", "existing-established"],),
    )
    db.execute(
        "DELETE FROM nodes WHERE id = ANY(%s)", (["brand-new-specimen", "existing-established"],)
    )


# --- identify -----------------------------------------------------------------------------------


def test_identify_known(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        llm,
        "vision_label",
        lambda *a, **kw: _label(
            template_guess="Doomer", confidence=0.9, overlaid_text="monday again"
        ),
    )
    _stub_resolution(monkeypatch, lambda name: "doomer")

    result = live.identify(b"bytes", "image/png")

    assert result.node_id == "doomer"
    assert result.trace_query is None
    assert result.guess == "Doomer"
    assert result.overlaid_text == "monday again"


def test_identify_unknown_with_guess(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        llm, "vision_label", lambda *a, **kw: _label(template_guess="New Thing", confidence=0.9)
    )
    _stub_resolution(monkeypatch, lambda name: None)

    result = live.identify(b"bytes", "image/png")

    assert result.node_id is None
    assert result.trace_query == "New Thing"
    assert result.guess == "New Thing"


def test_identify_unknown_without_guess(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        llm,
        "vision_label",
        lambda *a, **kw: _label(template_guess=None, confidence=0.1, description="an odd drawing"),
    )

    result = live.identify(b"bytes", "image/png")

    assert result.node_id is None
    assert result.trace_query == "an odd drawing"
    assert result.guess == "an odd drawing"


def test_identify_blanks_the_response_for_an_nsfw_image(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        llm,
        "vision_label",
        lambda *a, **kw: _label(
            template_guess="Doomer", confidence=0.95, nsfw=True, nsfw_reason="graphic gore"
        ),
    )
    _stub_resolution(monkeypatch, lambda name: "doomer")

    result = live.identify(b"bytes", "image/png")

    assert result.node_id is None
    assert result.trace_query is None
    assert result.guess is None
    assert result.overlaid_text is None


def test_identify_rejects_an_unsupported_type() -> None:
    with pytest.raises(ValueError):
        live.identify(b"bytes", "image/gif")


def test_identify_rejects_an_oversized_upload() -> None:
    with pytest.raises(ValueError):
        live.identify(b"x" * (5 * 1024 * 1024 + 1), "image/png")


# --- verify_signature ----------------------------------------------------------------------------


def _sign(secret: str, ts: int, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()


def test_verify_signature_accepts_a_good_signature() -> None:
    secret, ts, body = "whsec_test", 1_700_000_000, b'{"hello":"world"}'
    header = f"t={ts},v1={_sign(secret, ts, body)}"
    assert live.verify_signature(body, header, secret, now=float(ts + 10)) is True


def test_verify_signature_rejects_a_tampered_body() -> None:
    secret, ts = "whsec_test", 1_700_000_000
    header = f"t={ts},v1={_sign(secret, ts, b'original')}"
    assert live.verify_signature(b"tampered", header, secret, now=float(ts)) is False


def test_verify_signature_rejects_a_stale_timestamp() -> None:
    secret, ts, body = "whsec_test", 1_700_000_000, b"body"
    header = f"t={ts},v1={_sign(secret, ts, body)}"
    assert (
        live.verify_signature(body, header, secret, tolerance_s=300, now=float(ts + 1000)) is False
    )


def test_verify_signature_rejects_a_malformed_header() -> None:
    assert live.verify_signature(b"body", "not-a-valid-header", "secret") is False
    assert live.verify_signature(b"body", "t=abc,v1=xyz", "secret") is False


def test_guardrail_verdict_replaces_the_labellers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "label_nsfw_only", lambda image, mime: (True, "gore"))
    label = live._guardrail(b"img", "image/png", _label(nsfw=False))
    assert label.nsfw is True
    assert label.nsfw_reason == "gore"
    assert label.template_guess == "Doomer"  # the rest of the label is untouched


def test_guardrail_can_clear_an_image_the_labeller_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm, "label_nsfw_only", lambda image, mime: (False, None))
    label = live._guardrail(b"img", "image/png", _label(nsfw=True, nsfw_reason="maybe"))
    assert label.nsfw is False
    assert label.nsfw_reason is None


def test_guardrail_failure_keeps_the_labellers_verdict() -> None:
    flagged = _label(nsfw=True, nsfw_reason="graphic gore")
    assert live._guardrail(b"img", "image/png", flagged) == flagged  # the autouse stub fails


def test_guardrail_skips_an_image_the_labeller_was_blocked_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bytes] = []

    def judge(image: bytes, mime: str) -> tuple[bool, str | None]:
        calls.append(image)
        return False, None

    monkeypatch.setattr(llm, "label_nsfw_only", judge)
    blocked = _label(nsfw=True, nsfw_reason=llm.BLOCKED_REASON)
    assert live._guardrail(b"img", "image/png", blocked) == blocked
    assert calls == []


def test_tick_stores_the_guardrails_nsfw_verdict(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    post = _post("https://lemmy.test/post/guardrail-1", posted_at=now)
    monkeypatch.setattr(sources, "fetch", lambda feed: [post])
    monkeypatch.setattr(live, "get_settings", lambda: _settings())
    monkeypatch.setattr(live, "_download_image", lambda url: (b"data", "image/png"))
    monkeypatch.setattr(llm, "vision_label", lambda *a, **kw: _label(nsfw=False))
    monkeypatch.setattr(llm, "label_nsfw_only", lambda image, mime: (True, "gore"))
    _stub_resolution(monkeypatch, lambda name: "doomer")
    monkeypatch.setattr(trace, "run", lambda *a, **kw: None)

    live.tick(_FEED_KEY)

    row = db.fetch_one("SELECT nsfw, vision FROM sightings WHERE post_url = %s", (post.post_url,))
    assert row is not None
    assert row["nsfw"] is True
    assert row["vision"]["nsfw_reason"] == "gore"
