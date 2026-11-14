"""Manage Context.dev page monitors, one per feed, named "memepedia:<feed.key>".

`create` makes one monitor per feed, polling every 10 minutes (one credit per run) and sending
every run to `<PUBLIC_BASE_URL>/api/webhooks/context` as a signed `run.completed` event. Context.dev
issues each monitor its own signing secret; `create` stores it in the `webhook_monitors` table of
the active database (the production one when `.env` holds DATABASE_URL) and never prints it.
It skips every feed that already has a "memepedia:" monitor, so rerunning it after a partial
failure creates only the missing ones and can never double the spend.

`pause` and `resume` stop and restart polling without losing the monitors or their secrets
(a paused monitor costs nothing). `delete` removes the monitors and their stored secrets.
Every subcommand takes --dry-run, which prints what it would do and spends nothing (only `list`
style reads, which Context.dev does not charge for, are made). Only monitors whose name starts
with "memepedia:" are ever touched.

Usage: uv run python scripts/monitors.py create|list|pause|resume|delete [--dry-run]
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from typing import Any

from memepedia import contextdev, db, store
from memepedia.config import get_settings
from memepedia.live import feed_page_url
from memepedia.sources import FEEDS, Feed

_MONITOR_MINUTES = 10
_STAGGER_SECONDS = 5
_PREFIX = "memepedia:"


def _monitor_name(feed_key: str) -> str:
    return f"{_PREFIX}{feed_key}"


def _webhook_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/webhooks/context"


def _ours() -> list[dict[str, Any]]:
    return [m for m in contextdev.list_monitors() if str(m.get("name") or "").startswith(_PREFIX)]


def _create_one(feed: Feed, webhook: str) -> None:
    """Create one feed's monitor and store its signing secret, rotating one if none came back."""
    monitor = contextdev.create_monitor(
        _monitor_name(feed.key), feed_page_url(feed), minutes=_MONITOR_MINUTES, webhook_url=webhook
    )
    monitor_id = str(monitor["id"])
    secret = contextdev.webhook_secret_of(monitor) or contextdev.rotate_webhook_secret(monitor_id)
    store.save_monitor(monitor_id, feed.key, secret)
    stored = "secret stored" if secret else "NO SECRET: its deliveries will be refused"
    print(f"created {_monitor_name(feed.key)!r}: id={monitor_id}, {stored}")


def cmd_create(dry_run: bool) -> None:
    settings = get_settings()
    if not settings.public_base_url:
        raise SystemExit("PUBLIC_BASE_URL is not configured; refusing to create monitors.")
    webhook = _webhook_url(settings.public_base_url)
    existing = {str(m.get("name")) for m in _ours()}
    missing = [f for f in FEEDS if _monitor_name(f.key) not in existing]
    print(f"secrets go to: {db.describe_target()}; {len(existing)} exist, {len(missing)} to create")
    if not dry_run:
        db.init_schema()
    for i, feed in enumerate(missing):
        if dry_run:
            print(f"[dry-run] create {_monitor_name(feed.key)!r} watching {feed_page_url(feed)} "
                  f"every {_MONITOR_MINUTES}m -> {webhook} (run.completed)")  # fmt: skip
            continue
        _create_one(feed, webhook)
        if i < len(missing) - 1:
            time.sleep(_STAGGER_SECONDS)


def cmd_list(dry_run: bool) -> None:
    if dry_run:
        print("[dry-run] list monitors")
        return
    for monitor in contextdev.list_monitors():
        print(f"{monitor.get('id')}  {monitor.get('name')!r}  status={monitor.get('status')}")


def _each_ours(dry_run: bool, verb: str, act: Callable[[str], object]) -> None:
    for monitor in _ours():
        if dry_run:
            print(f"[dry-run] {verb} {monitor.get('name')!r} (id={monitor.get('id')})")
            continue
        act(str(monitor["id"]))
        print(f"{verb}d {monitor.get('name')!r}")


def _delete(monitor_id: str) -> None:
    contextdev.delete_monitor(monitor_id)
    store.delete_monitor_row(monitor_id)


def cmd_pause(dry_run: bool) -> None:
    _each_ours(dry_run, "pause", lambda mid: contextdev.set_monitor_status(mid, "paused"))


def cmd_resume(dry_run: bool) -> None:
    _each_ours(dry_run, "resume", lambda mid: contextdev.set_monitor_status(mid, "active"))


def cmd_delete(dry_run: bool) -> None:
    _each_ours(dry_run, "delete", _delete)


COMMANDS: dict[str, Callable[[bool], None]] = {
    "create": cmd_create,
    "list": cmd_list,
    "pause": cmd_pause,
    "resume": cmd_resume,
    "delete": cmd_delete,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Context.dev page monitors.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in COMMANDS:
        sub.add_parser(name).add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    COMMANDS[args.command](args.dry_run)


if __name__ == "__main__":
    main()
