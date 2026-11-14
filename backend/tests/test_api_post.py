"""The POST routes: thin wrappers whose errors and stream format the frontend depends on."""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import time
from collections.abc import Iterator, Mapping
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from memepedia import api, db, store
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
    for name in ("_trace_budget", "_identify_budget", "_proposal_budget", "_webhook_budget"):
        monkeypatch.setattr(api, name, api._Budget(100))
    db.execute("TRUNCATE webhook_events, webhook_monitors")


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


_SECRET = "whsec_monitor_1"
_RUN = {"id": "evt_1", "data": {"run": {"monitor_id": "mon_1"}, "change": None}}


def _signed(body: bytes, secret: str = _SECRET, event_id: str = "evt_1") -> dict[str, str]:
    ts = int(time.time())
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return {"X-Context-Signature": f"t={ts},v1={digest}", "X-Context-Id": event_id}


def _post(client: TestClient, body: bytes, headers: dict[str, str] | None = None) -> int:
    return client.post("/api/webhooks/context", content=body, headers=headers or {}).status_code


def test_webhook_runs_one_tick_per_event_signed_with_its_monitors_secret(
    client: TestClient, webhook_calls: list[Mapping[str, Any]]
) -> None:
    store.save_monitor("mon_1", "reddit:memes", _SECRET)
    body = json.dumps(_RUN).encode()
    assert _post(client, body, _signed(body)) == 200
    assert _post(client, body, _signed(body)) == 200
    assert webhook_calls == [_RUN]


def test_webhook_refuses_any_unsigned_caller_even_with_no_secret_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, webhook_calls: list[Mapping[str, Any]]
) -> None:
    settings = dataclasses.replace(get_settings(), webhook_secret=None)
    monkeypatch.setattr(api.live, "get_settings", lambda: settings)
    body = json.dumps(_RUN).encode()
    assert _post(client, body, {"X-Context-Id": "evt_1"}) == 401
    assert _post(client, body, _signed(body)) == 401
    assert webhook_calls == []


def test_webhook_refuses_a_signature_made_with_another_secret(
    client: TestClient, webhook_calls: list[Mapping[str, Any]]
) -> None:
    store.save_monitor("mon_1", "reddit:memes", _SECRET)
    body = json.dumps(_RUN).encode()
    assert _post(client, body, _signed(body, secret="whsec_forged")) == 401
    assert webhook_calls == []


def test_webhook_also_accepts_the_configured_env_secret(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, webhook_calls: list[Mapping[str, Any]]
) -> None:
    settings = dataclasses.replace(get_settings(), webhook_secret="whsec_env")
    monkeypatch.setattr(api.live, "get_settings", lambda: settings)
    body = json.dumps({"id": "evt_2"}).encode()
    assert _post(client, body, _signed(body, secret="whsec_env", event_id="evt_2")) == 200
    assert webhook_calls == [{"id": "evt_2"}]


def test_webhook_rejects_a_body_that_is_not_an_object(
    client: TestClient, webhook_calls: list[Mapping[str, Any]]
) -> None:
    assert _post(client, b"[1, 2]") == 400
    assert webhook_calls == []


def test_webhook_rejects_an_oversized_body(
    client: TestClient, webhook_calls: list[Mapping[str, Any]]
) -> None:
    assert _post(client, b" " * (api.MAX_WEBHOOK_BYTES + 1)) == 413
    assert webhook_calls == []


def test_webhook_is_rate_limited(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, webhook_calls: list[Mapping[str, Any]]
) -> None:
    monkeypatch.setattr(api, "_webhook_budget", api._Budget(1))
    body = json.dumps(_RUN).encode()
    assert [_post(client, body), _post(client, body)] == [401, 429]
