"""Fill the configured database with the mock archive fixtures.

Usage: uv run python scripts/load_fixtures.py [--reset]
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from memepedia import db, store
from memepedia.models import Link, MemeNode, Post

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "contract" / "fixtures"


def _load_json(name: str) -> Any:
    return json.loads((FIXTURES_DIR / name).read_text())


def _tree_files() -> list[dict[str, Any]]:
    return [_load_json(p.name) for p in sorted(FIXTURES_DIR.glob("tree-*.json"))]


def _collect_nodes() -> list[MemeNode]:
    return [MemeNode.model_validate(n) for n in _load_json("nodes.json")["nodes"]]


def _collect_links(trees: list[dict[str, Any]]) -> list[Link]:
    seen: dict[tuple[str, str], Link] = {}
    for tree in trees:
        for raw in tree["links"]:
            link = Link.model_validate(raw)
            seen[(link.child_id, link.axis)] = link
    return list(seen.values())


def _collect_sightings(trees: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    sightings: list[dict[str, Any]] = []
    tree_sightings = [s for tree in trees for s in tree["sightings"]]
    raw_all = _load_json("wall.json")["sightings"] + tree_sightings
    for raw in raw_all:
        if raw["id"] in seen_ids or raw["post_url"] in seen_urls:
            continue
        seen_ids.add(raw["id"])
        seen_urls.add(raw["post_url"])
        sightings.append(raw)
    return sightings


def _collect_history(trees: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**raw, "node_id": tree["selected_id"]} for tree in trees for raw in tree["history"]]


def _offset_for(sightings: list[dict[str, Any]]) -> timedelta:
    latest = max(datetime.fromisoformat(s["posted_at"]) for s in sightings)
    return datetime.now(UTC) - timedelta(minutes=2) - latest


def _load_nodes(nodes: list[MemeNode]) -> int:
    for node in nodes:
        store.upsert_node(node)
    return len(nodes)


def _load_links(links: list[Link]) -> int:
    for link in links:
        store.upsert_link(link)
    return len(links)


def _load_sightings(sightings: list[dict[str, Any]], offset: timedelta) -> int:
    known = store.known_post_urls([s["post_url"] for s in sightings])
    count = 0
    for raw in sightings:
        if raw["post_url"] in known:
            continue
        posted_at = datetime.fromisoformat(raw["posted_at"]) + offset
        post = Post.model_validate({**raw, "source": "fixture", "posted_at": posted_at})
        sid = store.insert_sighting(post, None, raw["node_id"], raw["state"])
        if sid is not None:
            db.execute("UPDATE sightings SET seen_at = %s WHERE id = %s", (posted_at, sid))
            count += 1
    return count


def _load_history(history: list[dict[str, Any]], offset: timedelta) -> int:
    rows = db.fetch_all("SELECT node_id, message FROM history")
    existing = {(r["node_id"], r["message"]) for r in rows}
    count = 0
    for raw in history:
        if (raw["node_id"], raw["message"]) in existing:
            continue
        ts = datetime.fromisoformat(raw["ts"]) + offset
        hid = store.add_history(
            type=raw["type"],
            node_id=raw["node_id"],
            message=raw["message"],
            source_url=raw["source_url"],
            pending=raw["pending"],
        )
        db.execute("UPDATE history SET ts = %s WHERE id = %s", (ts, hid))
        count += 1
    return count


def load(reset: bool = False) -> dict[str, int]:
    """Fill the database from the fixtures; returns a row count per table."""
    db.reset_schema() if reset else db.init_schema()
    nodes = _collect_nodes()
    trees = _tree_files()
    links = _collect_links(trees)
    sightings = _collect_sightings(trees)
    history = _collect_history(trees)
    offset = _offset_for(sightings)
    return {
        "nodes": _load_nodes(nodes),
        "links": _load_links(links),
        "sightings": _load_sightings(sightings, offset),
        "history": _load_history(history, offset),
    }


def main() -> None:
    """CLI entry point: load the fixtures, optionally resetting the schema first."""
    parser = argparse.ArgumentParser(description="Load the mock archive into the database.")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    counts = load(reset=args.reset)
    for table, count in counts.items():
        print(f"{table}: {count}")


if __name__ == "__main__":
    main()
