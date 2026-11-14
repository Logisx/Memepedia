"""Every fixture validates against its model, and every live endpoint matches the contract."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from memepedia import db, store
from memepedia.models import (
    IdentifyResponse,
    NodesResponse,
    Post,
    ProposalResponse,
    RandomResponse,
    RelatedResponse,
    TraceEvent,
    TreeResponse,
    VisionLabel,
    WallResponse,
    WeekResponse,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "contract" / "fixtures"


def _load(name: str) -> Any:
    return json.loads((FIXTURES_DIR / name).read_text())


def test_nodes_fixture_matches_model() -> None:
    NodesResponse.model_validate(_load("nodes.json"))


def test_wall_fixture_matches_model() -> None:
    WallResponse.model_validate(_load("wall.json"))


def test_week_fixture_matches_model() -> None:
    WeekResponse.model_validate(_load("week.json"))


@pytest.mark.parametrize(
    "name",
    ["tree-doomer.json", "tree-wojak.json", "tree-swole-doge-vs-cheems.json"],
)
def test_tree_fixtures_match_model(name: str) -> None:
    TreeResponse.model_validate(_load(name))


@pytest.mark.parametrize(
    "name",
    ["related-doomer-yes-chad.json", "related-swole-doge-vs-cheems-yes-chad.json"],
)
def test_related_fixtures_match_model(name: str) -> None:
    RelatedResponse.model_validate(_load(name))


def test_trace_sample_events_match_model() -> None:
    adapter = TypeAdapter(TraceEvent)
    for item in _load("trace-sample.json"):
        assert isinstance(item["delay_ms"], int)
        adapter.validate_python(item["event"])


def test_identify_fixture_entries_match_model() -> None:
    for entry in _load("identify.json"):
        IdentifyResponse.model_validate(entry)


def test_proposal_fixture_entries_match_model() -> None:
    for entry in _load("proposal.json"):
        ProposalResponse.model_validate(entry)


def test_wall_endpoint(client: TestClient) -> None:
    response = client.get("/api/wall")
    assert response.status_code == 200
    WallResponse.model_validate(response.json())


def test_wall_endpoint_accepts_sensitive_flag(client: TestClient) -> None:
    response = client.get("/api/wall", params={"sensitive": "true"})
    assert response.status_code == 200
    WallResponse.model_validate(response.json())


def test_nodes_endpoint(client: TestClient) -> None:
    response = client.get("/api/nodes", params={"q": "wojak"})
    assert response.status_code == 200
    NodesResponse.model_validate(response.json())


def test_nodes_random_endpoint(client: TestClient) -> None:
    response = client.get("/api/nodes/random")
    assert response.status_code == 200
    RandomResponse.model_validate(response.json())


def test_week_endpoint(client: TestClient) -> None:
    response = client.get("/api/week")
    assert response.status_code == 200
    WeekResponse.model_validate(response.json())


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["nodes"] > 0
    assert body["paid_work"] == "allowed"
    assert "last_webhook_s" in body


def test_tree_endpoint_includes_flagged_sightings_only_when_asked(client: TestClient) -> None:
    def post(name: str) -> Post:
        return Post(
            platform="lemmy",
            source="test",
            post_url=f"https://tree-sensitive.test/{name}",
            image_url=f"https://tree-sensitive.test/{name}.png",
            title=name,
            author="tester",
            posted_at=datetime.now(UTC),
        )

    sfw = store.insert_sighting(post("sfw"), None, "doomer", "resolved", nsfw=False)
    flagged = store.insert_sighting(post("flagged"), None, "doomer", "resolved", nsfw=True)
    unlabelled = store.insert_sighting(post("unlabelled"), None, "doomer", "resolved")
    try:
        default = client.get("/api/tree/doomer")
        assert default.status_code == 200
        default_ids = {
            x["id"]
            for x in TreeResponse.model_validate(default.json()).model_dump(mode="json")[
                "sightings"
            ]
        }
        assert sfw in default_ids
        assert flagged not in default_ids
        assert unlabelled not in default_ids

        asked = client.get("/api/tree/doomer", params={"sensitive": "true"})
        assert asked.status_code == 200
        asked_ids = {
            x["id"]
            for x in TreeResponse.model_validate(asked.json()).model_dump(mode="json")["sightings"]
        }
        assert {sfw, flagged, unlabelled} <= asked_ids
    finally:
        db.execute("DELETE FROM sightings WHERE post_url LIKE 'https://tree-sensitive.test/%%'")


def test_tree_unknown_id_is_404(client: TestClient) -> None:
    response = client.get("/api/tree/does-not-exist")
    assert response.status_code == 404
    assert "error" in response.json()


def test_related_unknown_id_is_404(client: TestClient) -> None:
    response = client.get("/api/related", params={"a": "doomer", "b": "does-not-exist"})
    assert response.status_code == 404
    assert "error" in response.json()


def test_related_endpoint(client: TestClient) -> None:
    response = client.get("/api/related", params={"a": "doomer", "b": "yes-chad"})
    assert response.status_code == 200
    body = RelatedResponse.model_validate(response.json())
    assert body.sentence


def _check_tree_consistency(body: dict[str, Any], node_id: str) -> None:
    node_ids = {n["id"] for n in body["nodes"]}
    assert body["selected_id"] == node_id
    assert node_id in node_ids
    assert set(body["family_ids"]) <= node_ids
    for link in body["links"]:
        assert link["child_id"] in node_ids
        assert link["parent_id"] in node_ids
    assert set(body["descent"]["character"]) <= node_ids
    assert set(body["descent"]["format"]) <= node_ids


def test_tree_endpoint_internally_consistent_for_every_node(client: TestClient) -> None:
    for node in store.all_nodes():
        response = client.get(f"/api/tree/{node.id}")
        assert response.status_code == 200, node.id
        body = response.json()
        TreeResponse.model_validate(body)
        _check_tree_consistency(body, node.id)


def test_wall_since_semantics(client: TestClient) -> None:
    first = client.get("/api/wall", params={"limit": 200})
    assert first.status_code == 200
    server_time = first.json()["server_time"]

    second = client.get("/api/wall", params={"since": server_time, "limit": 200})
    assert second.status_code == 200
    assert second.json()["sightings"] == []

    store.insert_sighting(
        Post(
            platform="lemmy",
            source="test",
            post_url="https://example.test/since-semantics-post",
            image_url="https://example.test/img.jpg",
            title="old post seen now",
            author="tester",
            posted_at=datetime(2020, 1, 1, tzinfo=UTC),
        ),
        VisionLabel(
            is_meme=True,
            template_guess="Doomer",
            confidence=0.95,
            structure_class=None,
            subjects=[],
            overlaid_text=None,
            catchphrase=None,
            description="",
            nsfw=False,
            nsfw_reason=None,
        ),
        "doomer",
        "resolved",
    )
    third = client.get("/api/wall", params={"since": server_time, "limit": 200})
    assert third.status_code == 200
    ids = {s["id"] for s in third.json()["sightings"]}
    assert store.sighting_id("https://example.test/since-semantics-post") in ids


def test_wall_endpoint_carries_a_next_before_cursor(client: TestClient) -> None:
    response = client.get("/api/wall", params={"limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert len(body["sightings"]) == 5
    assert body["next_before"] is not None


def test_wall_before_pagination_walks_backwards_without_duplicates_or_gaps(
    client: TestClient,
) -> None:
    whole = client.get("/api/wall", params={"limit": 1000})
    assert whole.status_code == 200
    all_ids = [s["id"] for s in whole.json()["sightings"]]
    assert len(all_ids) >= 6, "need enough sightings in the test database to page through"

    page_size = max(1, len(all_ids) // 3)
    seen: list[str] = []
    before: str | None = None
    for _ in range(len(all_ids) + 1):  # generous bound against an infinite loop on a bug
        params = {"limit": page_size}
        if before is not None:
            params["before"] = before
        page = client.get("/api/wall", params=params)
        assert page.status_code == 200
        body = page.json()
        seen.extend(s["id"] for s in body["sightings"])
        before = body["next_before"]
        if before is None:
            break
    else:
        raise AssertionError("before pagination never exhausted the wall")

    assert seen == all_ids, "paged-through ids must match the single-shot order exactly, in order"
    assert len(seen) == len(set(seen)), "no sighting should be returned twice across pages"


def test_wall_before_rejects_a_garbage_cursor(client: TestClient) -> None:
    response = client.get("/api/wall", params={"before": "not-a-cursor"})
    assert response.status_code == 400
    assert "error" in response.json()

    response = client.get("/api/wall", params={"before": "2020-01-01T00:00:00+00:00"})
    assert response.status_code == 400


def test_wall_before_caps_the_limit_at_100(client: TestClient) -> None:
    first_page = client.get("/api/wall", params={"limit": 1})
    assert first_page.status_code == 200
    cursor = first_page.json()["next_before"]
    assert cursor is not None

    response = client.get("/api/wall", params={"before": cursor, "limit": 10_000})
    assert response.status_code == 200
    assert len(response.json()["sightings"]) <= 100


def test_wall_order_is_deterministic_for_same_posted_at(client: TestClient) -> None:
    tied_at = datetime(2021, 6, 1, 12, 0, 0, tzinfo=UTC)
    ids = []
    for name in ("tie-a", "tie-b", "tie-c"):
        sid = store.insert_sighting(
            Post(
                platform="lemmy",
                source="test",
                post_url=f"https://example.test/order-tiebreak-{name}",
                image_url="https://example.test/img.jpg",
                title=name,
                author="tester",
                posted_at=tied_at,
            ),
            None,
            "doomer",
            "resolved",
            nsfw=False,
        )
        assert sid is not None
        ids.append(sid)
    try:
        first = client.get("/api/wall", params={"limit": 1000})
        assert first.status_code == 200
        order = [s["id"] for s in first.json()["sightings"] if s["id"] in ids]
        assert order == sorted(ids, reverse=True), "ties on posted_at must break on id DESC"

        # Running the same query twice gives the same order (nothing depends on scan order).
        second = client.get("/api/wall", params={"limit": 1000})
        order2 = [s["id"] for s in second.json()["sightings"] if s["id"] in ids]
        assert order2 == order
    finally:
        db.execute(
            "DELETE FROM sightings WHERE post_url LIKE 'https://example.test/order-tiebreak-%%'"
        )
