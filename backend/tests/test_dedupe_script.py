"""scripts/dedupe.py: fingerprint backfill, grouping and marking, with the downloader stubbed."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from memepedia import db, imageprep, live, store
from memepedia.models import Post
from scripts import dedupe as dedupe_script

_T0 = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def _fetch(url: str) -> live.Fetched:
    """A fingerprint per image URL; images under /same/ all share one, /broken/ ones fail."""
    if "/broken/" in url:
        return live.Fetched(None, "http_403")
    key = b"same" if "/same/" in url else url.encode()
    return live.Fetched(
        imageprep.Prepared(b"x", "image/jpeg", hashlib.sha256(key).hexdigest()), None
    )


@pytest.fixture
def restore_image_checks(client: TestClient) -> Iterator[None]:
    """Undo what the script writes onto the shared fixture rows (fingerprints and any marks)."""
    columns = "id, fingerprint, look_error, duplicate_of, state, node_id"
    before = db.fetch_all(f"SELECT {columns} FROM sightings")
    yield
    for row in before:
        db.execute(
            "UPDATE sightings SET fingerprint = %s, look_error = %s, duplicate_of = %s,"
            " state = %s, node_id = %s WHERE id = %s",
            (
                row["fingerprint"],
                row["look_error"],
                row["duplicate_of"],
                row["state"],
                row["node_id"],
                row["id"],
            ),
        )


def _insert(
    url: str, image_url: str, *, at: datetime, state: str = "pending", author: str = "a"
) -> str:
    post = Post(
        platform="reddit",
        source="test",
        post_url=url,
        image_url=image_url,
        title="It had a good run",
        author=author,
        posted_at=at,
    )
    node_id = "doomer" if state == "resolved" else None
    sid = store.insert_sighting(post, None, node_id, state)  # type: ignore[arg-type]
    assert sid is not None
    return sid


def test_dry_run_only_fingerprints_and_apply_marks_the_reposts(
    restore_image_checks: None,
) -> None:
    first = _insert("https://r.test/a", "https://img.test/same/1.jpg", at=_T0)
    resolved = _insert(
        "https://r.test/b",
        "https://img.test/same/2.jpg",
        at=_T0 + timedelta(hours=1),
        state="resolved",
    )
    broken = _insert("https://r.test/c", "https://img.test/broken/3.jpg", at=_T0)
    ids = [first, resolved, broken]
    try:
        report = dedupe_script.dedupe_archive(apply=False, workers=2, fetch=_fetch)
        rows = {
            r["id"]: r
            for r in db.fetch_all(
                "SELECT id, fingerprint, look_error, duplicate_of FROM sightings"
                " WHERE id = ANY(%s)",
                (ids,),
            )
        }
        assert rows[first]["fingerprint"] == rows[resolved]["fingerprint"] is not None
        assert rows[broken]["look_error"] == "http_403"
        assert all(r["duplicate_of"] is None for r in rows.values())
        mine = [g for g in report.groups if g.keeper["id"] in ids]
        assert len(mine) == 1
        # The resolved copy is kept even though it was posted later.
        assert mine[0].keeper["id"] == resolved
        assert [row["id"] for row, _ in mine[0].reposts] == [first]

        dedupe_script.dedupe_archive(apply=True, workers=2, fetch=_fetch)
        after = db.fetch_one(
            "SELECT duplicate_of, state, node_id FROM sightings WHERE id = %s", (first,)
        )
        assert after == {"duplicate_of": resolved, "state": "resolved", "node_id": "doomer"}
    finally:
        db.execute("UPDATE sightings SET duplicate_of = NULL WHERE id = ANY(%s)", (ids,))
        db.execute("DELETE FROM sightings WHERE id = ANY(%s)", (ids,))


def test_readable_url_rewrites_thumbnails_and_proxies() -> None:
    assert (
        live.readable_image_url("https://preview.redd.it/abcdefgh12.jpeg?width=140&amp;crop=1:1")
        == "https://i.redd.it/abcdefgh12.jpeg"
    )
    assert (
        live.readable_image_url(
            "https://lemmy.ml/api/v3/image_proxy?url=https%3A%2F%2Fa.test%2Fb.png"
        )
        == "https://a.test/b.png"
    )
