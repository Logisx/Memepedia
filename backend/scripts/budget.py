"""See and steer the cost guards (memepedia/budget.py) in the active database, no redeploy needed.

With a repo-root `.env` holding DATABASE_URL this is the production database, which the web
and clock containers read on every paid call; the target is printed first. Spends nothing.

    status              spend in the last 24h against each cap, kill switch, monitor heartbeat
    off                 kill switch on: every paid call is refused, the site keeps serving
    on                  kill switch off (the MEMEPEDIA_PAID_OFF env var, if set, still wins)
    cap KIND N          set the 24h cap on KIND (contextdev, gemini, traces) to N
    cap KIND default    drop the override, back to the env var or the built-in default

Usage: uv run python scripts/budget.py status|off|on|cap KIND N|default
"""

from __future__ import annotations

import argparse

from memepedia import budget, db, live, store


def _status_lines() -> list[str]:
    lines = [f"kill switch: {'ON' if budget.paid_off() else 'off'}"]
    for kind in budget.DEFAULT_CAPS:
        lines.append(
            f"{kind:10s} spent {budget.spent(kind):8g} of cap {budget.cap(kind):8g} "
            f"(background stops at {budget.limit(kind, background=True):g})"
        )
    age = store.state_age(live.HEARTBEAT_KEY)
    heartbeat = "never" if age is None else f"{age / 60:.1f} min ago"
    lines.append(f"last monitor webhook: {heartbeat}; stored monitors: {len(store.monitor_ids())}")
    lines.append(f"background work: {budget.background_block() or 'allowed'}")
    return lines


def _set_cap(kind: str, value: str) -> str:
    if kind not in budget.DEFAULT_CAPS:
        raise SystemExit(f"unknown kind {kind!r}; one of {', '.join(budget.DEFAULT_CAPS)}")
    if value == "default":
        store.clear_state(f"cap:{kind}")
    else:
        store.set_state(f"cap:{kind}", str(float(value)))
    return f"{kind} cap is now {budget.cap(kind):g}"


def run(command: str, args: list[str]) -> list[str]:
    """Carry out one command; returns the lines to print."""
    if command == "off":
        store.set_state(budget.KILL_SWITCH_KEY, "1")
    elif command == "on":
        store.clear_state(budget.KILL_SWITCH_KEY)
    elif command == "cap":
        if len(args) != 2:
            raise SystemExit("usage: cap KIND N|default")
        return [_set_cap(*args)]
    return _status_lines()


def main() -> None:
    parser = argparse.ArgumentParser(description="See and steer the cost guards.")
    parser.add_argument("command", choices=["status", "off", "on", "cap"])
    parser.add_argument("args", nargs="*")
    parsed = parser.parse_args()
    print(f"database: {db.describe_target()}")
    db.init_schema()
    for line in run(parsed.command, parsed.args):
        print(line)


if __name__ == "__main__":
    main()
