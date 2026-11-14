"""Build the real archive: curated families, Imgflip templates, images, and link verification.

Usage: uv run python scripts/seed.py [--reset] [--steps families,templates,images,verify]
       [--limit N] [--workers N]
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from memepedia import contextdev, db, images, llm, resolver, store, trace, verify
from memepedia.contextdev import ContextDevError
from memepedia.llm import LLMError
from memepedia.models import DraftChain, Link, MemeNode

logger = logging.getLogger("memepedia.seed")

SEED_JSON = Path(__file__).resolve().parent.parent / "memepedia" / "data" / "seed.json"
ALL_STEPS = ("families", "templates", "images", "verify")
DEFAULT_STEPS = ("families", "templates", "images")


def _domain(url: str) -> str:
    netloc = urlparse(url).netloc
    return netloc[4:] if netloc.startswith("www.") else netloc


def _load_seed() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(SEED_JSON.read_text())
    return data


def step_families() -> dict[str, int]:
    """Upsert every curated node and link; never overwrite an existing link or image."""
    data = _load_seed()
    node_count = 0
    for raw in data["nodes"]:
        existing = store.get_node(raw["id"])
        node = MemeNode(
            id=raw["id"],
            name=raw["name"],
            aliases=raw["aliases"],
            kind=raw["kind"],
            latin_name=raw["latin_name"],
            image_url=existing.image_url if existing else None,
            image_credit_url=existing.image_credit_url if existing else None,
            first_seen=raw["first_seen"],
            date_precision=raw["date_precision"],
            summary=raw["summary"],
            status="established",
            sightings_24h=0,
            sightings_7d=0,
        )
        store.upsert_node(node)
        node_count += 1

    link_count = 0
    for raw in data["links"]:
        if store.get_link(raw["child_id"], raw["axis"]) is not None:
            continue
        store.upsert_link(
            Link(
                child_id=raw["child_id"],
                parent_id=raw["parent_id"],
                axis=raw["axis"],
                status="inferred",
                quote=None,
                source_url=None,
                source_title=None,
            )
        )
        link_count += 1
    return {"nodes": node_count, "links": link_count}


def _draft_roots_and_candidates() -> tuple[list[llm.RootInfo], list[llm.Candidate]]:
    roots = [
        llm.RootInfo(id=r.id, name=r.name, summary=r.summary or "") for r in store.root_nodes()
    ]
    candidates = [llm.Candidate(n.id, n.name, n.kind, tuple(n.aliases)) for n in store.all_nodes()]
    return roots, candidates


def _draft_one(
    name: str, roots: list[llm.RootInfo], candidates: list[llm.Candidate]
) -> DraftChain | None:
    try:
        return llm.draft_chain(name, context=None, candidates=candidates, roots=roots)
    except LLMError:
        logger.warning("draft_chain failed for template %r", name, exc_info=True)
        return None


def step_templates(limit: int | None, workers: int) -> dict[str, int]:
    """Match or draft Imgflip's top templates, then attach their canonical image."""
    templates = images.top_templates()
    if limit is not None:
        templates = templates[:limit]
    index = store.name_index()
    to_draft = []
    matched = 0
    for template in templates:
        node_id = resolver.exact_match(index, template["name"])
        if node_id is None:
            to_draft.append(template)
            continue
        matched += 1
        node = store.get_node(node_id)
        if node is not None and node.image_url is None:
            store.set_node_image(node_id, template["url"], template["credit_url"])

    roots, candidates = _draft_roots_and_candidates()
    drafted = 0
    skipped = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_draft_one, t["name"], roots, candidates): t for t in to_draft}
        drafts: dict[str, DraftChain | None] = {}
        for future in as_completed(futures):
            template = futures[future]
            drafts[template["name"]] = future.result()

    for template in to_draft:
        draft = drafts.get(template["name"])
        if draft is None:
            print(f"templates: draft failed for {template['name']!r}")
            skipped += 1
            continue
        subject_id = trace.materialise(draft)
        if subject_id is None:
            print(f"templates: could not place {template['name']!r}")
            skipped += 1
            continue
        store.set_node_image(subject_id, template["url"], template["credit_url"])
        drafted += 1
    return {"matched": matched, "drafted": drafted, "skipped": skipped}


def step_images(workers: int) -> dict[str, int]:
    """Find an image for every node that lacks one and is not a format-class root."""
    nodes = [n for n in store.all_nodes() if n.image_url is None and n.kind != "format_class"]
    found = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(images.find_image, n.name, n.aliases): n for n in nodes}
        for future in as_completed(futures):
            node = futures[future]
            result = future.result()
            if result:
                store.set_node_image(node.id, result[0], result[1])
                found += 1
    return {"checked": len(nodes), "found": found}


def _verify_one(link: Link, nodes_by_id: dict[str, MemeNode]) -> tuple[Link, bool]:
    child, parent = nodes_by_id.get(link.child_id), nodes_by_id.get(link.parent_id)
    if child is None or parent is None:
        return link, False
    try:
        evidence = verify.find_evidence(child, parent, link.axis)
    except ContextDevError:
        logger.warning("find_evidence raised for %s -> %s", child.id, parent.id, exc_info=True)
        return link, False
    if evidence is None:
        return link, False
    updated = store.cite_link(link.child_id, link.axis, evidence)
    if updated is None:
        return link, False
    domain = _domain(evidence.source_url)
    store.add_history(
        "cited",
        link.child_id,
        f"Linked {child.name} to {parent.name} with a quote from {domain}.",
        source_url=evidence.source_url,
    )
    return updated, True


def step_verify(limit: int | None, workers: int) -> dict[str, int]:
    """Verify every inferred link (or up to `limit`) in parallel; print a line per link."""
    links = [link for link in store.all_links() if link.status == "inferred"]
    if limit is not None:
        links = links[:limit]
    nodes_by_id = {n.id: n for n in store.all_nodes()}
    cited = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_verify_one, link, nodes_by_id): link for link in links}
        for future in as_completed(futures):
            link = futures[future]
            _, ok = future.result()
            status = "cited" if ok else "still inferred"
            print(f"verify: {link.child_id} -> {link.parent_id} ({link.axis}): {status}")
            cited += 1 if ok else 0
    return {"checked": len(links), "cited": cited}


def _parse_steps(raw: str | None) -> Sequence[str]:
    if raw is None:
        return DEFAULT_STEPS
    steps = [s.strip() for s in raw.split(",") if s.strip()]
    unknown = [s for s in steps if s not in ALL_STEPS]
    if unknown:
        raise SystemExit(f"unknown step(s): {', '.join(unknown)} (choose from {ALL_STEPS})")
    return steps


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Build the Memepedia archive.")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--steps", type=str, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    db.reset_schema() if args.reset else db.init_schema()
    before = contextdev.credits_spent()
    for step in _parse_steps(args.steps):
        if step == "families":
            print("families:", step_families())
        elif step == "templates":
            print("templates:", step_templates(args.limit, args.workers))
        elif step == "images":
            print("images:", step_images(args.workers))
        elif step == "verify":
            print("verify:", step_verify(args.limit, args.workers))
    spent = contextdev.credits_spent() - before
    print(f"counts: {store.counts()}")
    print(f"credits spent this run: {spent:.1f}")


if __name__ == "__main__":
    main()
