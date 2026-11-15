"""A meme's page lists its posts with a `variant`, and a character's page also gets the posts
where it appears inside another meme's template."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from memepedia import db, store
from memepedia.models import Post, VisionLabel


def _label(**overrides: object) -> VisionLabel:
    base: dict[str, object] = dict(
        is_meme=True,
        template_guess=None,
        confidence=0.9,
        structure_class=None,
        subjects=[],
        overlaid_text=None,
        catchphrase=None,
        description="a test post",
        nsfw=False,
        nsfw_reason=None,
    )
    base.update(overrides)
    return VisionLabel(**base)  # type: ignore[arg-type]


def _post(url: str) -> Post:
    return Post(
        platform="lemmy",
        source="test",
        post_url=url,
        image_url=url + ".jpg",
        title="t",
        author="a",
        posted_at=datetime.now(UTC),
    )


@pytest.fixture
def posts(client: TestClient) -> Iterator[dict[str, str]]:
    made = {
        # Wojak drawn into another template: stamped with that template, names Wojak.
        "cross": store.insert_sighting(
            _post("https://tree.test/cross"),
            _label(template_guess="Swole Doge vs. Cheems", subjects=["Wojak"]),
            "swole-doge-vs-cheems",
            "resolved",
        ),
        # Wojak's own post whose guess names a different template.
        "own_variant": store.insert_sighting(
            _post("https://tree.test/own-variant"),
            _label(template_guess="Drake Hotline Bling", subjects=["Wojak"]),
            "wojak",
            "resolved",
        ),
        # Wojak's own post guessed as Wojak itself: no variant.
        "own_plain": store.insert_sighting(
            _post("https://tree.test/own-plain"),
            _label(template_guess="Wojak"),
            "wojak",
            "resolved",
        ),
    }
    ids = {k: v for k, v in made.items() if v is not None}
    assert len(ids) == 3
    yield ids
    db.execute("DELETE FROM sightings WHERE id = ANY(%s)", (list(ids.values()),))


def _tree(client: TestClient, node_id: str) -> dict[str, dict[str, object]]:
    response = client.get(f"/api/tree/{node_id}")
    assert response.status_code == 200
    return {s["id"]: s for s in response.json()["sightings"]}


def test_a_characters_page_includes_its_cross_template_posts(
    client: TestClient, posts: dict[str, str]
) -> None:
    shown = _tree(client, "wojak")
    assert shown[posts["cross"]]["variant"] == store.get_node("swole-doge-vs-cheems").name  # type: ignore[union-attr]
    assert shown[posts["cross"]]["node_id"] == "swole-doge-vs-cheems"
    assert shown[posts["own_variant"]]["variant"] == "Drake Hotline Bling"
    assert shown[posts["own_plain"]]["variant"] is None


def test_a_template_page_does_not_borrow_other_memes_posts(
    client: TestClient, posts: dict[str, str]
) -> None:
    shown = _tree(client, "swole-doge-vs-cheems")
    assert posts["cross"] in shown
    assert shown[posts["cross"]]["variant"] is None  # its guess is the template itself
    assert posts["own_variant"] not in shown


def test_the_wall_never_sets_a_variant(client: TestClient, posts: dict[str, str]) -> None:
    wall = client.get("/api/wall?limit=100").json()["sightings"]
    assert all(s["variant"] is None for s in wall)


def test_a_page_shows_up_to_48_posts(client: TestClient) -> None:
    ids = [
        store.insert_sighting(_post(f"https://tree.test/many-{i}"), _label(), "wojak", "resolved")
        for i in range(50)
    ]
    try:
        assert len(store.sightings_for_node("wojak")) == 48
    finally:
        db.execute("DELETE FROM sightings WHERE id = ANY(%s)", ([i for i in ids if i],))
