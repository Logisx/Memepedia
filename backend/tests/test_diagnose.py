"""scripts/diagnose.py runs on the test database, finds a mention, and writes nothing."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from memepedia import db, store
from memepedia.models import Post, VisionLabel
from scripts import diagnose


def test_the_snapshot_runs_and_lists_posts_naming_a_meme(client: TestClient) -> None:
    post = Post(
        platform="lemmy",
        source="test",
        post_url="https://diag.test/pov-doomer",
        image_url="https://diag.test/pov-doomer.jpg",
        title="POV: you are the Doomer",
        author="a",
        posted_at=datetime.now(UTC),
    )
    label = VisionLabel(
        is_meme=True,
        template_guess=None,
        confidence=0.3,
        structure_class=None,
        subjects=["a man in a beanie"],
        overlaid_text=None,
        catchphrase=None,
        description="a tired figure",
        nsfw=False,
        nsfw_reason=None,
    )
    sid = store.insert_sighting(post, label, None, "pending")
    assert sid is not None
    try:
        before = db.fetch_all("SELECT id, state, node_id FROM sightings ORDER BY id")
        lines: list[str] = []
        diagnose.report("Doomer", out=lines.append)
        text = "\n".join(lines)
        assert "== sightings by state / read / nsfw / repost ==" in text
        assert sid in text
        assert "POV: you are the Doomer" in text
        assert "== orphans: unclassified memes with no stamp ==" in text
        assert db.fetch_all("SELECT id, state, node_id FROM sightings ORDER BY id") == before
    finally:
        db.execute("DELETE FROM sightings WHERE id = %s", (sid,))


def test_the_columns_check_sees_the_new_columns(client: TestClient) -> None:
    assert {"look_error", "duplicate_of", "fingerprint"} <= diagnose.sightings_columns()
