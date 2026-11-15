"""scripts/relook.py: each mode's dry run and --apply, with the downloader and models stubbed."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Json

from memepedia import db, imageprep, live, llm, store
from memepedia.models import Post, VisionLabel
from scripts import relook


def _label(**overrides: object) -> VisionLabel:
    base: dict[str, object] = dict(
        is_meme=True,
        template_guess="Doomer",
        confidence=0.95,
        structure_class=None,
        subjects=[],
        overlaid_text=None,
        catchphrase=None,
        description="a tired figure",
        nsfw=False,
        nsfw_reason=None,
    )
    base.update(overrides)
    return VisionLabel(**base)  # type: ignore[arg-type]


def _post(url: str, image_url: str, title: str = "t") -> Post:
    return Post(
        platform="reddit",
        source="test",
        post_url=url,
        image_url=image_url,
        title=title,
        author="a",
        posted_at=datetime.now(UTC),
    )


def _fetch(url: str) -> live.Fetched:
    if "broken" in url:
        return live.Fetched(None, "http_403")
    fp = hashlib.sha256(url.encode()).hexdigest()
    return live.Fetched(imageprep.Prepared(b"x", "image/jpeg", fp), None)


@pytest.fixture
def stubs(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """No downloads, a fixed Doomer label, no guardrail call; yields the vision calls' titles."""
    calls: list[str] = []

    def fake_label(*a: object, title: str | None = None, **kw: object) -> VisionLabel:
        calls.append(title or "")
        return _label()

    monkeypatch.setattr(live, "fetch_image", _fetch)
    monkeypatch.setattr(llm, "vision_label", fake_label)
    monkeypatch.setattr(
        llm, "label_nsfw_only", lambda *a: (_ for _ in ()).throw(llm.LLMUnavailable("stub"))
    )
    yield calls


_COLUMNS = ("vision", "state", "node_id", "nsfw", "image_url", "look_error", "fingerprint")


@pytest.fixture(autouse=True)
def restore_fixture_rows(client: TestClient) -> Iterator[None]:
    """`--apply` also relabels the shared fixture rows (they have no vision); put them back."""
    before = db.fetch_all(f"SELECT id, {', '.join(_COLUMNS)} FROM sightings")
    yield
    assignments = ", ".join(f"{c} = %s" for c in _COLUMNS)
    for row in before:
        values = [Json(row["vision"]) if row["vision"] is not None else None]
        values += [row[c] for c in _COLUMNS[1:]]
        db.execute(f"UPDATE sightings SET {assignments} WHERE id = %s", (*values, row["id"]))


@pytest.fixture
def made() -> Iterator[list[str]]:
    ids: list[str] = []
    yield ids
    db.execute("DELETE FROM sightings WHERE id = ANY(%s)", (ids,))


def _insert(made: list[str], post: Post, vision: VisionLabel | None, state: str) -> str:
    sid = store.insert_sighting(post, vision, None, state)  # type: ignore[arg-type]
    assert sid is not None
    made.append(sid)
    return sid


def _row(sid: str) -> db.Row:
    row = db.fetch_one(
        "SELECT state, node_id, vision, look_error, image_url, nsfw FROM sightings WHERE id = %s",
        (sid,),
    )
    assert row is not None
    return row


def test_unread_dry_run_changes_nothing(stubs: list[str], made: list[str]) -> None:
    thumb = "https://preview.redd.it/abcdefgh12.jpeg?width=140&amp;crop=1:1"
    sid = _insert(made, _post("https://r.test/relook-1", thumb), None, "unclassified")
    report = relook.relook("unread", apply=False)
    assert stubs == []
    assert any(sid in line and "i.redd.it/abcdefgh12.jpeg" in line for line in report.lines)
    assert _row(sid)["vision"] is None and _row(sid)["image_url"] == thumb


def test_unread_apply_labels_stamps_and_records_failures(stubs: list[str], made: list[str]) -> None:
    thumb = "https://preview.redd.it/abcdefgh13.jpeg?width=140&amp;crop=1:1"
    ok = _insert(made, _post("https://r.test/relook-2", thumb), None, "unclassified")
    broken = _insert(
        made, _post("https://r.test/relook-3", "https://img.test/broken.jpg"), None, "unclassified"
    )
    report = relook.relook("unread", apply=True, max_n=10)
    assert report.changed >= 1
    row = _row(ok)
    assert (row["state"], row["node_id"]) == ("resolved", "doomer")
    assert row["image_url"] == "https://i.redd.it/abcdefgh13.jpeg"
    assert row["vision"]["template_guess"] == "Doomer" and row["nsfw"] is False
    assert _row(broken)["look_error"] == "http_403"
    assert _row(broken)["vision"] is None


def test_max_caps_how_many_images_are_labelled(stubs: list[str], made: list[str]) -> None:
    for i in range(3):
        _insert(
            made,
            _post(f"https://r.test/relook-max-{i}", f"https://img.test/m{i}.jpg"),
            None,
            "unclassified",
        )
    relook.relook("unread", apply=True, max_n=1)
    assert len(stubs) == 1


def test_not_memes_are_labelled_again(stubs: list[str], made: list[str]) -> None:
    sid = _insert(
        made,
        _post("https://r.test/relook-nm", "https://img.test/nm.jpg", title="Dear Hackers"),
        _label(is_meme=False, template_guess=None),
        "unclassified",
    )
    relook.relook("not-memes", apply=True, max_n=50)
    assert "Dear Hackers" in stubs
    assert _row(sid)["state"] == "resolved"


def test_orphans_go_back_to_pending_without_any_model_call(
    stubs: list[str], made: list[str]
) -> None:
    meme = _insert(
        made,
        _post("https://r.test/relook-or1", "https://img.test/or1.jpg"),
        _label(),
        "unclassified",
    )
    photo = _insert(
        made,
        _post("https://r.test/relook-or2", "https://img.test/or2.jpg"),
        _label(is_meme=False),
        "unclassified",
    )
    dry = relook.relook("orphans", apply=False)
    assert _row(meme)["state"] == "unclassified" and dry.changed == 0
    relook.relook("orphans", apply=True)
    assert _row(meme)["state"] == "pending"
    assert _row(photo)["state"] == "unclassified"
    assert stubs == []
