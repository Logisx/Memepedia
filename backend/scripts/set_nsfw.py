"""Manually set one node's or sighting's nsfw flag, overriding the backfill or vision label.

Usage: uv run python scripts/set_nsfw.py <node|sighting> <id> <true|false>
"""

from __future__ import annotations

import argparse

from memepedia import db, store


def _parse_bool(value: str) -> bool:
    if value.lower() in ("true", "1", "yes"):
        return True
    if value.lower() in ("false", "0", "no"):
        return False
    raise argparse.ArgumentTypeError(f"expected true or false, got {value!r}")


def _sighting_exists(sighting_id: str) -> bool:
    return db.fetch_one("SELECT id FROM sightings WHERE id = %s", (sighting_id,)) is not None


def main() -> None:
    parser = argparse.ArgumentParser(description="Manually set a node's or sighting's nsfw flag.")
    parser.add_argument("kind", choices=["node", "sighting"])
    parser.add_argument("id")
    parser.add_argument("value", type=_parse_bool)
    args = parser.parse_args()

    db.init_schema()
    if args.kind == "node":
        if store.get_node(args.id) is None:
            raise SystemExit(f"unknown node {args.id!r}")
        store.set_node_nsfw(args.id, args.value)
    else:
        if not _sighting_exists(args.id):
            raise SystemExit(f"unknown sighting {args.id!r}")
        store.set_sighting_nsfw(args.id, args.value)
    print(f"{args.kind} {args.id}: nsfw = {args.value}")


if __name__ == "__main__":
    main()
