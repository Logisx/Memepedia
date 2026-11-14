"""Every fixture validates against its model, and every live endpoint matches the contract."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from memepedia import store
from memepedia.models import (
    IdentifyResponse,
    NodesResponse,
    Post,
    ProposalResponse,
    RandomResponse,
    RelatedResponse,
    TraceEvent,
    TreeResponse,
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
        None,
        "doomer",
        "resolved",
    )
    third = client.get("/api/wall", params={"since": server_time, "limit": 200})
    assert third.status_code == 200
    ids = {s["id"] for s in third.json()["sightings"]}
    assert store.sighting_id("https://example.test/since-semantics-post") in ids
