"""The POST routes: thin wrappers whose errors and stream format the frontend depends on."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator, Mapping
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from memepedia import api
from memepedia.config import get_settings
from memepedia.llm import LLMError
from memepedia.models import (
    DoneEvent,
    IdentifyResponse,
    ProposalResponse,
    StatusEvent,
    TraceEvent,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture(autouse=True)
def fresh_budgets(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("_trace_budget", "_identify_budget", "_proposal_budget"):
        monkeypatch.setattr(api, name, api._Budget(100))
    api._seen_deliveries.clear()


def _events(body: str) -> list[Any]:
    adapter: TypeAdapter[Any] = TypeAdapter(TraceEvent)
    frames = [frame for frame in body.split("\n\n") if frame]
    assert all(frame.startswith("data: ") for frame in frames)
    return [adapter.validate_json(frame.removeprefix("data: ")) for frame in frames]


def test_trace_streams_contract_events(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_trace(query: str) -> Iterator[Any]:
        yield StatusEvent(message=f"Searching the archive for {query}…")
        yield DoneEvent(node_id="doomer")

    monkeypatch.setattr(api.trace, "trace", fake_trace)
    response = client.post("/api/trace", json={"query": "  Doomer "})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    assert [event.type for event in events] == ["status", "done"]
    assert events[0].message == "Searching the archive for Doomer…"


def test_trace_rejects_an_empty_query(client: TestClient) -> None:
    response = client.post("/api/trace", json={"query": "   "})
    assert response.status_code == 400
    assert "error" in response.json()


def test_trace_refuses_when_the_minute_is_spent(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api, "_trace_budget", api._Budget(0))
    response = client.post("/api/trace", json={"query": "Doomer"})
    assert response.status_code == 429
    assert "error" in response.json()


def test_budget_allows_up_to_its_limit() -> None:
    budget = api._Budget(2)
    budget.take()
    budget.take()
    with pytest.raises(HTTPException) as refused:
        budget.take()
    assert refused.value.status_code == 429


def test_identify_passes_the_upload_through(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[bytes, str]] = []

    def fake_identify(image: bytes, mime_type: str) -> IdentifyResponse:
        seen.append((image, mime_type))
        return IdentifyResponse(
            node_id="doomer", trace_query=None, guess="Doomer", overlaid_text=None
        )

    monkeypatch.setattr(api.live, "identify", fake_identify)
    response = client.post("/api/identify", files={"image": ("meme.png", PNG, "image/png")})
    assert response.status_code == 200
    assert IdentifyResponse.model_validate(response.json()).node_id == "doomer"
    assert seen == [(PNG, "image/png")]


@pytest.mark.parametrize(
    ("raised", "status"),
    [(ValueError("Only JPEG, PNG and WebP images are accepted."), 400), (LLMError("down"), 503)],
)
def test_identify_errors_follow_the_contract(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, raised: Exception, status: int
) -> None:
    def failing(image: bytes, mime_type: str) -> IdentifyResponse:
        raise raised

    monkeypatch.setattr(api.live, "identify", failing)
    response = client.post("/api/identify", files={"image": ("meme.gif", PNG, "image/gif")})
    assert response.status_code == status
    assert set(response.json()) == {"error"}


def test_proposal_returns_the_verdict(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_propose(node_id: str, url: str, note: str) -> ProposalResponse:
        return ProposalResponse(accepted=False, message=f"{node_id}|{url}|{note}", link=None)

    monkeypatch.setattr(api.trace, "propose", fake_propose)
    body = {"node_id": "doomer", "url": " https://example.org/doomer ", "note": " see para 2 "}
    response = client.post("/api/proposals", json=body)
    assert response.status_code == 200
    verdict = ProposalResponse.model_validate(response.json())
    assert verdict.message == "doomer|https://example.org/doomer|see para 2"


def test_proposal_for_an_unknown_node_is_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unknown(node_id: str, url: str, note: str) -> ProposalResponse:
        raise LookupError(node_id)

    monkeypatch.setattr(api.trace, "propose", unknown)
    response = client.post("/api/proposals", json={"node_id": "nope", "url": "https://x.org"})
    assert response.status_code == 404
    assert response.json() == {"error": "Unknown node."}


@pytest.fixture
def webhook_calls(monkeypatch: pytest.MonkeyPatch) -> list[Mapping[str, Any]]:
    calls: list[Mapping[str, Any]] = []
    monkeypatch.setattr(api.live, "handle_webhook", calls.append)
    return calls


def test_webhook_triggers_one_tick_per_event(
    client: TestClient, webhook_calls: list[Mapping[str, Any]]
) -> None:
    payload = {"id": "evt_1", "data": {"run": {"monitor_id": "mon_1"}, "change": None}}
    headers = {"X-Context-Event": "run.completed", "X-Context-Id": "evt_1"}
    first = client.post("/api/webhooks/context", json=payload, headers=headers)
    retry = client.post("/api/webhooks/context", json=payload, headers=headers)
    assert first.status_code == retry.status_code == 200
    assert webhook_calls == [payload]


def test_webhook_rejects_a_body_that_is_not_an_object(
    client: TestClient, webhook_calls: list[Mapping[str, Any]]
) -> None:
    response = client.post("/api/webhooks/context", content=b"[1, 2]")
    assert response.status_code == 400
    assert webhook_calls == []


def test_webhook_checks_the_signature_when_a_secret_is_set(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, webhook_calls: list[Mapping[str, Any]]
) -> None:
    settings = dataclasses.replace(get_settings(), webhook_secret="whsec_test")
    monkeypatch.setattr(api, "get_settings", lambda: settings)
    verdicts = iter([False, True])
    monkeypatch.setattr(api.live, "verify_signature", lambda raw, header, secret: next(verdicts))
    body = json.dumps({"id": "evt_2"})
    refused = client.post("/api/webhooks/context", content=body)
    accepted = client.post("/api/webhooks/context", content=body)
    assert (refused.status_code, accepted.status_code) == (401, 200)
    assert webhook_calls == [{"id": "evt_2"}]
