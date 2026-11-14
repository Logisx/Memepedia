"""Hard cost guards, kept in Postgres so the web and clock containers share them across restarts.

Three kinds of paid work are counted per hour (`store.add_spend`) and summed over a rolling
window: Context.dev credits (`contextdev`), Gemini calls (`gemini`) and traces the background
loop starts (`traces`). Each kind has a cap: a default here, overridden by the environment
(`MEMEPEDIA_CAP_<KIND>`), overridden in turn by the database (`cap:<kind>` in `app_state`, set
with `scripts/budget.py`, no redeploy needed). Background work (feed ticks, the backfill) stops
`RESERVE` short of a cap, so visitors' traces still work after a busy night; the chokepoints in
`contextdev` and `llm` refuse any call once the cap itself is reached. The kill switch
(`MEMEPEDIA_PAID_OFF=1`, or `paid_off` = 1 in `app_state`) refuses all paid work at once.
Reading the site never spends anything, so it keeps serving whatever the guards say.

The check and the spend are not one transaction, so concurrent workers can overshoot a cap by
the few calls already in flight. That is accepted: the caps are a safety net, not an invoice.
"""

from __future__ import annotations

import os

from memepedia import store
from memepedia.config import get_settings

WINDOW_HOURS = 24
DEFAULT_CAPS = {"contextdev": 3000.0, "gemini": 5000.0, "traces": 10.0}
RESERVE = {"contextdev": 500.0, "gemini": 500.0, "traces": 0.0}
BACKGROUND_KINDS = ("contextdev", "gemini")
KILL_SWITCH_KEY = "paid_off"
_TRUTHY = {"1", "true", "on", "yes"}


def _env(name: str) -> str | None:
    get_settings()  # loads the repo's .env into the environment, once
    return os.environ.get(name)


def charge(kind: str, amount: float) -> None:
    """Count `amount` units of `kind` as spent now; nothing for zero or less."""
    if amount > 0:
        store.add_spend(kind, amount)


def spent(kind: str) -> float:
    """Units of `kind` spent within the rolling window."""
    return store.spend_total(kind, WINDOW_HOURS)


def cap(kind: str) -> float:
    """The cap on `kind` per window: the database override, else the environment, else default."""
    value = store.get_state(f"cap:{kind}") or _env(f"MEMEPEDIA_CAP_{kind.upper()}")
    return float(value) if value else DEFAULT_CAPS[kind]


def paid_off() -> bool:
    """Whether the kill switch is on, in the environment or in the database."""
    if (_env("MEMEPEDIA_PAID_OFF") or "").strip().lower() in _TRUTHY:
        return True
    return store.get_state(KILL_SWITCH_KEY) == "1"


def limit(kind: str, *, background: bool) -> float:
    """How much of `kind` may be spent per window; background work leaves the reserve unspent."""
    return cap(kind) - (RESERVE[kind] if background else 0.0)


def headroom(kind: str, *, background: bool = True) -> float:
    """Units of `kind` still allowed in this window; 0 while the kill switch is on."""
    if paid_off():
        return 0.0
    return max(0.0, limit(kind, background=background) - spent(kind))


def block_reason(kind: str, *, background: bool = False) -> str | None:
    """Why paid work of `kind` must not run now, or None when it may."""
    if paid_off():
        return "the kill switch is on"
    allowed, used = limit(kind, background=background), spent(kind)
    if used >= allowed:
        return f"{kind} cap reached ({used:g} of {allowed:g} in {WINDOW_HOURS}h)"
    return None


def background_block() -> str | None:
    """Why the background loop must not spend now, or None when it may."""
    for kind in BACKGROUND_KINDS:
        reason = block_reason(kind, background=True)
        if reason is not None:
            return reason
    return None


def claim(key: str, every_s: float) -> bool:
    """Take a turn that comes round at most once per `every_s`, shared by every container."""
    return store.claim_turn(f"throttle:{key}", every_s)
