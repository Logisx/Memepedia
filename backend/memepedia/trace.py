"""Hypothesise a meme's lineage with an LLM, verify it against the live web, and serve proposals."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import date
from urllib.parse import urlparse

from memepedia import contextdev, graph, images, llm, resolver, store, verify
from memepedia.contextdev import ContextDevError
from memepedia.models import (
    Axis,
    ChainEvent,
    DoneEvent,
    DraftChain,
    DraftNode,
    ErrorEvent,
    Link,
    LinkEvent,
    MemeNode,
    ProposalResponse,
    StatusEvent,
    TraceEvent,
)

logger = logging.getLogger("memepedia.trace")

_VERIFY_WORKERS = 4
_VERIFY_DEADLINE_S = 60.0
_IMAGE_WORKERS = 4
_IMAGE_DEADLINE_S = 8.0
_WEB_CONTEXT_CHARS = 1500


def _domain(url: str) -> str:
    netloc = urlparse(url).netloc
    return netloc[4:] if netloc.startswith("www.") else netloc


def _web_context(query: str) -> str:
    try:
        hits = contextdev.search(f"{query} meme", num_results=5, label="trace_context")
    except ContextDevError:
        logger.warning("web context search failed for %r", query)
        return ""
    parts = []
    for hit in hits:
        text = verify.clean_text(hit.markdown or "")[:_WEB_CONTEXT_CHARS]
        parts.append(f"## {hit.title or hit.url}\n{hit.url}\n{text}")
    return "\n\n".join(parts)


def _resolve_draft_node(draft: DraftChain, draft_node: DraftNode, *, as_specimen: bool) -> str:
    if draft_node.existing_id and store.get_node(draft_node.existing_id) is not None:
        return draft_node.existing_id
    hit = resolver.resolve(draft_node.name, hint=draft_node.summary)
    if hit is not None:
        return hit
    node_id = resolver.free_id(draft_node.name)
    is_subject = draft_node.name == draft.subject
    status = "specimen" if (is_subject and as_specimen) else "established"
    first_seen, precision = draft_node.first_seen, draft_node.date_precision
    if is_subject and as_specimen and first_seen is None:
        first_seen, precision = date.today(), "day"
    store.upsert_node(
        MemeNode(
            id=node_id,
            name=draft_node.name,
            aliases=draft_node.aliases,
            kind=draft_node.kind,
            latin_name=draft_node.latin_name,
            image_url=None,
            image_credit_url=None,
            first_seen=first_seen,
            date_precision=precision,
            summary=draft_node.summary,
            status=status,
            sightings_24h=0,
            sightings_7d=0,
        )
    )
    return node_id


def _materialise_nodes(
    draft: DraftChain, *, as_specimen: bool
) -> tuple[dict[str, str], dict[str, MemeNode]]:
    name_to_id: dict[str, str] = {}
    nodes_by_id: dict[str, MemeNode] = {}
    for draft_node in draft.nodes:
        node_id = _resolve_draft_node(draft, draft_node, as_specimen=as_specimen)
        node = store.get_node(node_id)
        if node is None:
            continue
        name_to_id[draft_node.name] = node_id
        nodes_by_id[node_id] = node
    return name_to_id, nodes_by_id


def _materialise_links(
    draft: DraftChain, name_to_id: dict[str, str], nodes_by_id: dict[str, MemeNode]
) -> list[Link]:
    links = store.all_links()
    for draft_link in draft.links:
        child_id = name_to_id.get(draft_link.child)
        parent_id = name_to_id.get(draft_link.parent)
        if child_id is None or parent_id is None or child_id == parent_id:
            continue
        if store.get_link(child_id, draft_link.axis) is not None:
            continue
        if graph.creates_cycle(links, child_id, parent_id, draft_link.axis):
            continue
        if graph.parent_is_younger(nodes_by_id[child_id], nodes_by_id[parent_id]):
            continue
        link = Link(
            child_id=child_id,
            parent_id=parent_id,
            axis=draft_link.axis,
            status="inferred",
            quote=None,
            source_url=None,
            source_title=None,
        )
        store.upsert_link(link)
        links.append(link)
    return links


def _draft_root_id(draft: DraftChain, name_to_id: dict[str, str]) -> str | None:
    for draft_node in draft.nodes:
        if draft_node.kind == "format_class" and draft_node.name in name_to_id:
            return name_to_id[draft_node.name]
    return None


def _attach_rootless(subject_id: str, links: list[Link], root_id: str | None) -> bool:
    """Attaches a dangling chain to a root if possible; False only when it cannot be placed."""
    chain = graph.lineage(links, subject_id)
    top = store.get_node(chain[-1])
    if top is None:
        return False
    if top.kind == "format_class":
        return True
    if root_id is None:
        return False
    axis: Axis = "format" if top.kind in ("template", "phrase") else "character"
    if store.get_link(top.id, axis) is not None:
        return True
    if graph.creates_cycle(links, top.id, root_id, axis):
        return True
    link = Link(
        child_id=top.id,
        parent_id=root_id,
        axis=axis,
        status="inferred",
        quote=None,
        source_url=None,
        source_title=None,
    )
    store.upsert_link(link)
    links.append(link)
    return True


def materialise(draft: DraftChain, *, as_specimen: bool = False) -> str | None:
    """Writes a draft into the archive; returns the subject's node id, or None if unusable."""
    if not draft.subject or not draft.nodes:
        return None
    name_to_id, nodes_by_id = _materialise_nodes(draft, as_specimen=as_specimen)
    subject_id = name_to_id.get(draft.subject)
    if subject_id is None:
        return None
    links = _materialise_links(draft, name_to_id, nodes_by_id)
    root_id = _draft_root_id(draft, name_to_id)
    if not _attach_rootless(subject_id, links, root_id):
        return None
    subject = store.get_node(subject_id)
    assert subject is not None
    chain = graph.lineage(links, subject_id)
    root = store.get_node(chain[-1])
    assert root is not None
    hops = len(chain) - 1
    plural = "" if hops == 1 else "s"
    store.add_history(
        "traced",
        subject_id,
        f"Traced {subject.name} back to {root.name} through {hops} link{plural}.",
    )
    return subject_id


def _lookup_images(node_ids: set[str]) -> None:
    nodes = [
        n
        for n in store.get_nodes(list(node_ids))
        if n.image_url is None and n.kind != "format_class"
    ]
    if not nodes:
        return
    with ThreadPoolExecutor(max_workers=_IMAGE_WORKERS) as pool:
        futures = {pool.submit(images.find_image, n.name, n.aliases): n for n in nodes}
        try:
            for future in as_completed(futures, timeout=_IMAGE_DEADLINE_S):
                node = futures[future]
                try:
                    result = future.result()
                except Exception:
                    logger.warning("image lookup failed for %s", node.id, exc_info=True)
                    continue
                if result:
                    store.set_node_image(node.id, result[0], result[1])
        except FutureTimeoutError:
            logger.info("image lookup deadline reached for %d node(s)", len(nodes))


def _chain_ids(subject_id: str, links: list[Link]) -> list[str]:
    character = graph.lineage(links, subject_id)
    fmt = graph.descent(links, subject_id, "format")
    return list(dict.fromkeys([*character, *fmt]))


def _verify_one(link: Link, nodes_by_id: dict[str, MemeNode]) -> Link | None:
    child, parent = nodes_by_id.get(link.child_id), nodes_by_id.get(link.parent_id)
    if child is None or parent is None:
        return None
    evidence = verify.find_evidence(child, parent, link.axis)
    if evidence is None:
        return None
    updated = store.cite_link(link.child_id, link.axis, evidence)
    if updated is None:
        return None
    domain = _domain(evidence.source_url)
    store.add_history(
        "cited",
        link.child_id,
        f"Linked {child.name} to {parent.name} with a quote from {domain}.",
        source_url=evidence.source_url,
    )
    return updated


def _verify_links(links: list[Link], nodes_by_id: dict[str, MemeNode]) -> Iterator[TraceEvent]:
    if not links:
        return
    with ThreadPoolExecutor(max_workers=_VERIFY_WORKERS) as pool:
        futures = {pool.submit(_verify_one, link, nodes_by_id): link for link in links}
        try:
            for future in as_completed(futures, timeout=_VERIFY_DEADLINE_S):
                try:
                    updated = future.result()
                except Exception:
                    logger.warning("link verification raised", exc_info=True)
                    continue
                if updated is not None:
                    yield LinkEvent(link=updated)
        except FutureTimeoutError:
            logger.info("verification deadline reached for %d link(s)", len(links))


def trace(
    query: str, *, context: str | None = None, as_specimen: bool = False
) -> Iterator[TraceEvent]:
    """Streams the contract's trace events for `query`; never raises."""
    try:
        yield StatusEvent(message="Searching the archive…")
        node_id = resolver.resolve(query)
        if node_id is not None:
            links = store.all_links()
            ids = graph.lineage(links, node_id)
            nodes = store.get_nodes(ids)
            chain_links = [link for link in links if link.child_id in ids and link.parent_id in ids]
            yield ChainEvent(nodes=nodes, links=chain_links)
            yield DoneEvent(node_id=node_id)
            return

        yield StatusEvent(message="Hypothesising a lineage…")
        roots = [
            llm.RootInfo(id=r.id, name=r.name, summary=r.summary or "") for r in store.root_nodes()
        ]
        candidates = [
            llm.Candidate(n.id, n.name, n.kind, tuple(n.aliases)) for n in store.all_nodes()
        ]
        draft = llm.draft_chain(query, context=context, candidates=candidates, roots=roots)
        if not draft.known and context is None:
            yield StatusEvent(message="Unfamiliar. Reading the open web…")
            draft = llm.draft_chain(
                query, context=_web_context(query), candidates=candidates, roots=roots
            )
        if not draft.subject or not draft.nodes:
            yield ErrorEvent(message="Could not find or hypothesise a lineage for this meme.")
            return

        subject_id = materialise(draft, as_specimen=as_specimen)
        if subject_id is None:
            yield ErrorEvent(message="Could not place this meme in the archive.")
            return

        links = store.all_links()
        ids = _chain_ids(subject_id, links)
        _lookup_images(set(ids))
        nodes = store.get_nodes(ids)
        chain_links = [link for link in links if link.child_id in ids and link.parent_id in ids]
        yield ChainEvent(nodes=nodes, links=chain_links)

        nodes_by_id = {n.id: n for n in nodes}
        inferred = [link for link in chain_links if link.status == "inferred"]
        yield from _verify_links(inferred, nodes_by_id)
        yield DoneEvent(node_id=subject_id)
    except Exception:
        logger.exception("trace failed for query %r", query)
        yield ErrorEvent(message="Something went wrong while tracing this meme.")


def run(query: str, *, context: str | None = None, as_specimen: bool = False) -> str | None:
    """Drains `trace(...)`, returning the subject's node id, or None on error."""
    node_id: str | None = None
    for event in trace(query, context=context, as_specimen=as_specimen):
        if event.type == "done":
            node_id = event.node_id
    return node_id


def _proposal_candidates(
    node: MemeNode, links: list[Link]
) -> list[tuple[MemeNode, MemeNode, Axis]]:
    candidates: list[tuple[MemeNode, MemeNode, Axis]] = []
    for axis in ("character", "format"):
        link = store.get_link(node.id, axis)
        if link is not None and link.status == "inferred":
            parent = store.get_node(link.parent_id)
            if parent is not None:
                candidates.append((node, parent, axis))
    for link in links:
        if link.parent_id == node.id and link.status == "inferred":
            child = store.get_node(link.child_id)
            if child is not None:
                candidates.append((child, node, link.axis))
    return candidates


def propose(node_id: str, url: str, note: str) -> ProposalResponse:
    """Checks a visitor-suggested URL against a node's inferred links; cites one if it qualifies."""
    node = store.get_node(node_id)
    if node is None:
        raise LookupError(f"unknown node {node_id!r}")
    if not url.lower().startswith(("http://", "https://")):
        return ProposalResponse(
            accepted=False, message="Please provide a valid http(s) URL.", link=None
        )
    if "knowyourmeme.com" in url:
        return ProposalResponse(
            accepted=False,
            message="Know Your Meme can't be used as a source; please link a different page.",
            link=None,
        )
    try:
        scraped = contextdev.scrape(url, formats={"markdown": True}, label="proposal")
    except ContextDevError:
        logger.warning("proposal scrape failed for %s", url, exc_info=True)
        return ProposalResponse(accepted=False, message="Could not read that page.", link=None)
    if not scraped.markdown:
        return ProposalResponse(
            accepted=False, message="That page had no readable text.", link=None
        )

    candidates = _proposal_candidates(node, store.all_links())
    if not candidates:
        store.add_history(
            "proposal",
            node_id,
            f"Visitor suggested {url}",
            source_url=url,
            pending=True,
            payload={"note": note},
        )
        return ProposalResponse(
            accepted=False, message="This meme has no unverified links to check against.", link=None
        )

    for child, parent, axis in candidates:
        evidence = verify.evidence_in_page(
            child, parent, axis, markdown=scraped.markdown, url=url, title=scraped.title or url
        )
        if evidence is None:
            continue
        updated = store.cite_link(child.id, axis, evidence)
        if updated is None:
            continue
        domain = _domain(url)
        store.add_history(
            "cited",
            child.id,
            f"Linked {child.name} to {parent.name} with a quote from {domain}.",
            source_url=url,
        )
        store.add_history(
            "proposal",
            node_id,
            f"Visitor-suggested source accepted: {url}",
            source_url=url,
            pending=False,
            payload={"note": note},
        )
        return ProposalResponse(
            accepted=True,
            message=f"Added a citation linking {child.name} to {parent.name}.",
            link=updated,
        )

    store.add_history(
        "proposal",
        node_id,
        f"Visitor suggested {url}",
        source_url=url,
        pending=True,
        payload={"note": note},
    )
    return ProposalResponse(
        accepted=False,
        message="That page didn't contain a sentence we could use as a citation.",
        link=None,
    )
