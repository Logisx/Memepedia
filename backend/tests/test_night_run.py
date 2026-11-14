"""The night run: webhook handling, the guarded tick, the clock fallback, the operator scripts."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from memepedia import budget, contextdev, db, live, store
from memepedia.sources import FEEDS
from scripts import backfill
from scripts import budget as budget_script
from scripts import monitors as monitors_script

_FEED = "reddit:memes"
_CHANGE = {"id": "chg_1", "monitor_id": "mon_1"}


def _delivery(change: object = _CHANGE, **run: object) -> dict[str, Any]:
    return {"id": "evt_1", "data": {"run": {"monitor_id": "mon_1", **run}, "change": change}}


@pytest.fixture(autouse=True)
def clean_guards(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("MEMEPEDIA_PAID_OFF", raising=False)
    monkeypatch.setattr(live, "_monitor_feed_cache", {})
    db.execute("TRUNCATE spend, app_state, webhook_monitors, webhook_events")
    yield
    db.execute("TRUNCATE spend, app_state, webhook_monitors, webhook_events")


@pytest.fixture
def ticks(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Feeds the guarded tick reached; the real tick and its housekeeping are stubbed out."""
    seen: list[str] = []

    def fake_tick(feed_key: str) -> live.TickReport:
        seen.append(feed_key)
        return live.TickReport(feed_key, 0, 0, 0, 0, 0, 0, [], [])

    monkeypatch.setattr(live, "tick", fake_tick)
    monkeypatch.setattr(live, "maintenance", lambda: None)
    return seen


@pytest.fixture
def paused(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        contextdev, "set_monitor_status", lambda mid, status: calls.append((mid, status))
    )
    return calls


# --- handle_webhook --------------------------------------------------------------------------


def test_a_changed_page_ticks_its_feed_and_counts_the_run(ticks: list[str]) -> None:
    store.save_monitor("mon_1", _FEED, "whsec_x")
    assert live.handle_webhook(_delivery(status="completed", credits_charged=1)) == _FEED
    assert ticks == [_FEED]
    assert budget.spent("contextdev") == 1
    assert store.state_age(live.HEARTBEAT_KEY) is not None


def test_an_unchanged_page_ticks_nothing_but_still_counts_and_beats(ticks: list[str]) -> None:
    store.save_monitor("mon_1", _FEED, "whsec_x")
    assert live.handle_webhook(_delivery(change=None, status="completed")) is None
    assert ticks == []
    assert budget.spent("contextdev") == 1
    assert store.state_age(live.HEARTBEAT_KEY) is not None


def test_a_skipped_run_costs_nothing(ticks: list[str]) -> None:
    store.save_monitor("mon_1", _FEED, "whsec_x")
    live.handle_webhook(_delivery(change=None, status="skipped"))
    assert budget.spent("contextdev") == 0


def test_an_unknown_monitor_ticks_nothing(
    ticks: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(contextdev, "list_monitors", lambda: [])
    assert live.handle_webhook(_delivery()) is None
    assert live.handle_webhook({"data": {}}) is None
    assert ticks == []


def test_a_monitor_missing_from_the_table_is_found_by_name_once(
    ticks: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    lists: list[int] = []

    def fake_list() -> list[dict[str, str]]:
        lists.append(1)
        return [{"id": "mon_1", "name": f"memepedia:{_FEED}"}]

    monkeypatch.setattr(contextdev, "list_monitors", fake_list)
    assert live.handle_webhook(_delivery()) == _FEED
    assert live._feed_for_monitor("mon_1") == _FEED
    assert lists == [1]


def test_webhook_secrets_prefer_the_monitors_own_secret() -> None:
    store.save_monitor("mon_1", _FEED, "whsec_own")
    assert live.webhook_secrets(_delivery())[0] == "whsec_own"
    assert live.authentic(b"{}", "t=1,v1=00", _delivery()) is False


# --- guarded_tick and the clock -------------------------------------------------------------


def test_guarded_tick_runs_a_feed_at_most_once_per_interval(ticks: list[str]) -> None:
    assert live.guarded_tick(_FEED) is not None
    assert live.guarded_tick(_FEED) is None
    assert ticks == [_FEED]


def test_guarded_tick_spends_nothing_and_pauses_monitors_once_a_cap_is_reached(
    ticks: list[str], paused: list[tuple[str, str]]
) -> None:
    store.save_monitor("mon_1", _FEED, "whsec_x")
    store.set_state("cap:gemini", "600")
    budget.charge("gemini", 600 - budget.RESERVE["gemini"])
    assert live.guarded_tick(_FEED) is None
    assert live.guarded_tick("imgflip:fun") is None
    assert ticks == []
    assert paused == [("mon_1", "paused")]


def test_the_kill_switch_stops_the_guarded_tick(
    ticks: list[str], paused: list[tuple[str, str]]
) -> None:
    store.set_state(budget.KILL_SWITCH_KEY, "1")
    assert live.guarded_tick(_FEED) is None
    assert ticks == []


def test_background_traces_stop_at_their_cap() -> None:
    store.set_state("cap:traces", "1")
    assert live._trace_turn_refused() is None
    assert "traces cap reached" in (live._trace_turn_refused() or "")


def test_the_clock_idles_while_webhooks_arrive_and_stands_in_when_they_stop(
    ticks: list[str],
) -> None:
    assert live.clock_tick(_FEED).startswith("TickReport")
    assert ticks == [_FEED]
    store.set_state(live.HEARTBEAT_KEY, "mon_1")
    assert live.clock_tick("imgflip:fun").startswith("idle")
    assert ticks == [_FEED]


# --- operator scripts -----------------------------------------------------------------------


def test_budget_script_turns_the_kill_switch_and_caps() -> None:
    assert "kill switch: ON" in budget_script.run("off", [])
    assert budget.paid_off() is True
    assert "kill switch: off" in budget_script.run("on", [])
    assert budget_script.run("cap", ["gemini", "42"]) == ["gemini cap is now 42"]
    budget_script.run("cap", ["gemini", "default"])
    assert budget.cap("gemini") == budget.DEFAULT_CAPS["gemini"]


def test_backfill_looks_at_no_more_images_than_the_budget_allows() -> None:
    store.set_state("cap:gemini", str(budget.RESERVE["gemini"] + 30))
    assert backfill._affordable(120) == 30
    store.set_state(budget.KILL_SWITCH_KEY, "1")
    assert backfill._affordable(120) == 0


def test_create_stores_each_monitors_secret_and_rotates_when_none_came_back(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    created = iter([{"id": "mon_a", "webhook": {"secret": "whsec_a"}}, {"id": "mon_b"}])
    monkeypatch.setattr(contextdev, "create_monitor", lambda *a, **k: next(created))
    monkeypatch.setattr(contextdev, "rotate_webhook_secret", lambda mid: f"whsec_{mid}")
    monitors_script._create_one(FEEDS[0], "https://x/api/webhooks/context")
    monitors_script._create_one(FEEDS[1], "https://x/api/webhooks/context")
    assert store.monitor_row("mon_a") == (FEEDS[0].key, "whsec_a")
    assert store.monitor_row("mon_b") == (FEEDS[1].key, "whsec_mon_b")
    assert "whsec" not in capsys.readouterr().out


def test_create_skips_feeds_that_already_have_a_monitor(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    existing = [{"id": f"m{i}", "name": f"memepedia:{f.key}"} for i, f in enumerate(FEEDS)]
    monkeypatch.setattr(contextdev, "list_monitors", lambda: existing)
    monkeypatch.setattr(contextdev, "create_monitor", pytest.fail)
    monkeypatch.setattr(
        monitors_script, "get_settings", lambda: type("S", (), {"public_base_url": "https://x"})
    )
    monitors_script.cmd_create(dry_run=False)
    assert f"{len(FEEDS)} exist, 0 to create" in capsys.readouterr().out
