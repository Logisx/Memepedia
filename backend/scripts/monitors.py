"""Manage Context.dev page monitors, one per feed, named "memepedia:<feed.key>".

Every subcommand takes --dry-run, which prints what it would do and calls nothing. `create`
refuses to run without PUBLIC_BASE_URL. `delete` only ever touches monitors whose name starts
with "memepedia:".

Usage: uv run python scripts/monitors.py create|list|delete [--dry-run]
"""

from __future__ import annotations

import argparse
import time

from memepedia import contextdev
from memepedia.config import get_settings
from memepedia.live import feed_page_url
from memepedia.sources import FEEDS

_MONITOR_MINUTES = 10
_STAGGER_SECONDS = 5


def _monitor_name(feed_key: str) -> str:
    return f"memepedia:{feed_key}"


def _webhook_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/webhooks/context"


def cmd_create(dry_run: bool) -> None:
    settings = get_settings()
    if not settings.public_base_url:
        raise SystemExit("PUBLIC_BASE_URL is not configured; refusing to create monitors.")
    webhook = _webhook_url(settings.public_base_url)
    for i, feed in enumerate(FEEDS):
        name, url = _monitor_name(feed.key), feed_page_url(feed)
        if dry_run:
            print(
                f"[dry-run] create {name!r} watching {url} every {_MONITOR_MINUTES}m -> {webhook}"
            )
            continue
        monitor = contextdev.create_monitor(
            name, url, minutes=_MONITOR_MINUTES, webhook_url=webhook
        )
        print(f"created {name!r}: id={monitor.get('id')}")
        if i < len(FEEDS) - 1:
            time.sleep(_STAGGER_SECONDS)


def cmd_list(dry_run: bool) -> None:
    if dry_run:
        print("[dry-run] list monitors")
        return
    for monitor in contextdev.list_monitors():
        print(f"{monitor.get('id')}  {monitor.get('name')!r}  status={monitor.get('status')}")


def cmd_delete(dry_run: bool) -> None:
    ours = [
        m for m in contextdev.list_monitors() if str(m.get("name") or "").startswith("memepedia:")
    ]
    for monitor in ours:
        if dry_run:
            print(f"[dry-run] delete {monitor.get('name')!r} (id={monitor.get('id')})")
            continue
        contextdev.delete_monitor(str(monitor["id"]))
        print(f"deleted {monitor.get('name')!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Context.dev page monitors.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "list", "delete"):
        sub.add_parser(name).add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    {"create": cmd_create, "list": cmd_list, "delete": cmd_delete}[args.command](args.dry_run)


if __name__ == "__main__":
    main()
