"""The re-match script: dry run by default, no LLM unless asked, and a cap when it is."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from memepedia import db, llm, store
from memepedia.config import Settings
from memepedia.llm import Candidate
from memepedia.models import Post, VisionLabel
from scripts import rematch

_PREFIX = "https://rematch.test/"


def _settings() -> Settings:
    return Settings(
        database_url=None,
        local_db_name="memepedia_test",
        contextdev_key=None,
        gemini_key=None,
        gemini_model="test-model",
        public_base_url=None,
        vision_per_tick=10,
        vision_min_confidence=0.85,
        auto_traces_per_tick=1,
    )


def _label(**overrides: object) -> VisionLabel:
    base: dict[str, object] = dict(
        is_meme=True,
        template_guess=None,
        confidence=0.0,
        structure_class=None,
        subjects=[],
        overlaid_text=None,
        catchphrase=None,
        description="a figure",
        nsfw=False,
        nsfw_reason=None,
    )
    base.update(overrides)
    return VisionLabel(**base)


def _add(name: str, label: VisionLabel) -> str:
    post = Post(
        platform="lemmy",
        source="test",
        post_url=_PREFIX + name,
        image_url=_PREFIX + name + ".png",
        title=name,
        author="tester",
        posted_at=datetime.now(UTC),
    )
    sid = store.insert_sighting(post, label, None, "pending")
    assert sid is not None
    return sid


def _state(sid: str) -> tuple[str, str | None]:
    row = db.fetch_one("SELECT state, node_id FROM sightings WHERE id = %s", (sid,))
    assert row is not None
    return row["state"], row["node_id"]


@pytest.fixture
def pending(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """Three pending sightings: an exact guess, a depicted character, and a hopeless one."""
    monkeypatch.setattr(rematch, "get_settings", _settings)
    ids = {
        "exact": _add("exact", _label(template_guess="Doomer", confidence=0.75)),
        "subject": _add("subject", _label(subjects=["a man", "Wojak"])),
        "none": _add("none", _label(template_guess="Xqzv Blorptangle", confidence=0.95)),
    }
    yield ids
    db.execute("DELETE FROM sightings WHERE post_url LIKE %s", (_PREFIX + "%",))


def _mine(report: rematch.RematchReport, ids: dict[str, str]) -> dict[str, rematch.Proposal]:
    wanted = {sid: name for name, sid in ids.items()}
    return {wanted[p.sighting_id]: p for p in report.proposals if p.sighting_id in wanted}


def test_dry_run_proposes_but_changes_nothing(pending: dict[str, str]) -> None:
    report = rematch.rematch(apply=False, hours=None, llm_enabled=False, max_llm=0)
    found = _mine(report, pending)
    assert {name: (p.node_id, p.via) for name, p in found.items()} == {
        "exact": ("doomer", "exact"),
        "subject": ("wojak", "subject"),
    }
    assert report.applied == 0
    assert all(_state(sid) == ("pending", None) for sid in pending.values())


def test_apply_stamps_only_the_matches(pending: dict[str, str]) -> None:
    report = rematch.rematch(apply=True, hours=None, llm_enabled=False, max_llm=0)
    assert report.applied >= 2
    assert _state(pending["exact"]) == ("resolved", "doomer")
    assert _state(pending["subject"]) == ("resolved", "wojak")
    assert _state(pending["none"]) == ("pending", None)


def test_without_llm_a_near_guess_is_counted_not_asked(
    pending: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(name: str, *, hint: str | None, candidates: Sequence[Candidate]) -> str | None:
        raise AssertionError("the LLM must not be called without --llm")

    monkeypatch.setattr(llm, "same_or_new", boom)
    near = _add("near", _label(template_guess="Doomer Wojak", confidence=0.95))
    report = rematch.rematch(apply=False, hours=None, llm_enabled=False, max_llm=50)
    assert report.llm_used == 0
    assert report.llm_skipped >= 1
    assert near not in {p.sighting_id for p in report.proposals}


def test_llm_checks_stop_at_the_cap(
    pending: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def fake(name: str, *, hint: str | None, candidates: Sequence[Candidate]) -> str | None:
        asked.append(name)
        return "doomer"

    monkeypatch.setattr(llm, "same_or_new", fake)
    monkeypatch.setattr(store, "add_alias", lambda node_id, alias: None)
    _add("near-1", _label(template_guess="Doomer Wojak", confidence=0.95))
    _add("near-2", _label(template_guess="Doomer Boy", confidence=0.95))
    report = rematch.rematch(apply=False, hours=None, llm_enabled=True, max_llm=1)
    assert report.llm_used == 1  # however many other pending rows there are, the cap holds
    assert report.llm_skipped >= 1
    assert len(asked) == 1


def test_parse_stored_vision_accepts_a_row_from_before_new_fields() -> None:
    label = llm.parse_stored_vision(
        {"is_meme": True, "template_guess": "Doomer", "confidence": "0.8"}
    )
    assert (label.template_guess, label.confidence, label.subjects, label.nsfw) == (
        "Doomer",
        0.8,
        [],
        False,
    )
    assert llm.parse_stored_vision({}).is_meme is False
