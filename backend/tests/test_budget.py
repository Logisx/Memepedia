"""The cost guards: spend, caps, the kill switch, throttles, and the two paid-call chokepoints."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import BaseModel

from memepedia import budget, contextdev, db, llm, store


@pytest.fixture(autouse=True)
def clean_guards(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in ("MEMEPEDIA_PAID_OFF", "MEMEPEDIA_CAP_CONTEXTDEV", "MEMEPEDIA_CAP_GEMINI"):
        monkeypatch.delenv(name, raising=False)
    db.execute("TRUNCATE spend, app_state")
    yield
    db.execute("TRUNCATE spend, app_state")


def test_charge_adds_up_within_the_window_and_ignores_nothing_spent() -> None:
    budget.charge("contextdev", 2)
    budget.charge("contextdev", 3.5)
    budget.charge("contextdev", 0)
    assert budget.spent("contextdev") == 5.5
    assert budget.spent("gemini") == 0


def test_spend_older_than_the_window_does_not_count() -> None:
    db.execute(
        "INSERT INTO spend (hour, kind, amount) "
        "VALUES (date_trunc('hour', now()) - interval '24 hours', 'gemini', 99)"
    )
    budget.charge("gemini", 1)
    assert budget.spent("gemini") == 1


def test_cap_comes_from_the_database_then_the_environment_then_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert budget.cap("gemini") == budget.DEFAULT_CAPS["gemini"]
    monkeypatch.setenv("MEMEPEDIA_CAP_GEMINI", "1234")
    assert budget.cap("gemini") == 1234
    store.set_state("cap:gemini", "77")
    assert budget.cap("gemini") == 77


def test_background_work_stops_at_the_reserve_but_visitors_may_spend_it() -> None:
    store.set_state("cap:contextdev", "1000")
    budget.charge("contextdev", 1000 - budget.RESERVE["contextdev"])
    assert budget.block_reason("contextdev", background=True) is not None
    assert budget.background_block() is not None
    assert budget.block_reason("contextdev") is None
    budget.charge("contextdev", budget.RESERVE["contextdev"])
    assert "cap reached" in (budget.block_reason("contextdev") or "")


def test_the_kill_switch_blocks_everything_from_the_database_or_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert budget.background_block() is None
    store.set_state(budget.KILL_SWITCH_KEY, "1")
    assert budget.block_reason("gemini") == "the kill switch is on"
    assert budget.headroom("gemini") == 0
    store.clear_state(budget.KILL_SWITCH_KEY)
    monkeypatch.setenv("MEMEPEDIA_PAID_OFF", "1")
    assert budget.paid_off() is True


def test_claim_gives_one_turn_per_interval() -> None:
    assert budget.claim("tick:x", 300) is True
    assert budget.claim("tick:x", 300) is False
    assert budget.claim("tick:y", 300) is True
    assert budget.claim("tick:x", 0) is True


def _no_http(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("no HTTP call may be made once the budget refuses")


def test_contextdev_refuses_paid_calls_once_its_cap_is_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(contextdev, "_request", _no_http)
    store.set_state("cap:contextdev", "10")
    budget.charge("contextdev", 10)
    with pytest.raises(contextdev.CreditCapReached):
        contextdev.scrape("https://example.org", formats={"markdown": True}, label="t")
    with pytest.raises(contextdev.CreditCapReached):
        contextdev.search("doge", label="t")
    with pytest.raises(contextdev.CreditCapReached):
        contextdev.create_monitor("memepedia:x", "https://example.org")


def test_contextdev_records_each_calls_credits_in_the_shared_spend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setattr(contextdev.config, "DATA_DIR", tmp_path)
    contextdev._record_credit("/web/scrape", "t", 3.0, 0.1, 200)
    assert budget.spent("contextdev") == 3.0


class _Answer(BaseModel):
    ok: bool


class _FakeModels:
    def __init__(self) -> None:
        self.calls = 0

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls += 1
        return type("Response", (), {"text": '{"ok": true}'})()


class _FakeClient:
    def __init__(self) -> None:
        self.models = _FakeModels()


def test_gemini_counts_each_call_and_refuses_once_the_kill_switch_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient()
    monkeypatch.setattr(llm, "_get_client", lambda: client)
    assert llm._generate("hi", response_schema=_Answer, temperature=0.0) == '{"ok": true}'
    assert budget.spent("gemini") == 1
    store.set_state(budget.KILL_SWITCH_KEY, "1")
    with pytest.raises(llm.GeminiCapReached):
        llm._generate("hi", response_schema=_Answer, temperature=0.0)
    assert client.models.calls == 1


def test_a_refused_gemini_call_is_an_llm_error_callers_already_handle() -> None:
    assert issubclass(llm.GeminiCapReached, llm.LLMError)
    assert issubclass(contextdev.CreditCapReached, contextdev.ContextDevError)
