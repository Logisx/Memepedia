"""The public Memepedia API: exactly the contract's GET routes."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from memepedia import db, graph, store
from memepedia.models import (
    Descent,
    Kind,
    Link,
    NodesResponse,
    RandomResponse,
    RelatedResponse,
    TreeResponse,
    WallResponse,
    WeekResponse,
)
from memepedia.sources import FEEDS

log = logging.getLogger("memepedia.api")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    db.init_schema()
    yield


app = FastAPI(title="Memepedia API", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


@app.exception_handler(HTTPException)
def _handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    return _error(str(exc.detail), exc.status_code)


@app.exception_handler(RequestValidationError)
def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return _error("Invalid request parameters.", 400)


@app.exception_handler(Exception)
def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return _error("Internal server error.", 500)


@app.get("/api/wall", response_model=WallResponse)
def get_wall(since: str | None = None, limit: int = 60) -> WallResponse:
    """Recent sightings; pass back server_time as `since` on the next poll."""
    since_dt = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError as exc:
            raise HTTPException(400, "Invalid 'since' timestamp.") from exc
    sightings, cursor = store.wall_page(since_dt, limit)
    return WallResponse(sightings=sightings, server_time=cursor, sources_watched=len(FEEDS))


@app.get("/api/nodes", response_model=NodesResponse)
def get_nodes_route(q: str = "", limit: int = 20) -> NodesResponse:
    """Search nodes by name or alias; an empty q returns a popular mix."""
    return NodesResponse(nodes=store.search_nodes(q, limit))


@app.get("/api/nodes/random", response_model=RandomResponse)
def get_random_node() -> RandomResponse:
    """A random established, non-format_class node id."""
    node_id = store.random_node_id()
    if node_id is None:
        raise HTTPException(404, "The archive is empty.")
    return RandomResponse(id=node_id)


def _tree_node_ids(
    links: list[Link], kinds: dict[str, Kind], node_id: str, family_ids: list[str]
) -> tuple[set[str], list[str], list[str], set[str]]:
    char_descent = graph.lineage(links, node_id)
    format_descent = graph.descent(links, node_id, "format")
    direct_children = {link.child_id for link in links if link.parent_id == node_id}
    node_ids = {node_id, *family_ids, *char_descent, *format_descent}
    if kinds.get(node_id) == "format_class":
        node_ids |= direct_children
    return node_ids, char_descent, format_descent, direct_children


@app.get("/api/tree/{node_id}", response_model=TreeResponse)
def get_tree(node_id: str) -> TreeResponse:
    """The family, descent chains, links, sightings and history for one node."""
    selected = store.get_node(node_id)
    if selected is None:
        raise HTTPException(404, "Unknown node.")
    links = store.all_links()
    kinds = {n.id: n.kind for n in store.all_nodes()}
    family = graph.family_ids(links, kinds, node_id)
    node_ids, char_descent, format_descent, direct_children = _tree_node_ids(
        links, kinds, node_id, family
    )
    link_set = [link for link in links if link.child_id in node_ids and link.parent_id in node_ids]
    history_ids = {node_id, *direct_children}
    return TreeResponse(
        selected_id=node_id,
        nodes=store.get_nodes(sorted(node_ids)),
        family_ids=family,
        links=link_set,
        descent=Descent(character=char_descent, format=format_descent),
        sightings=store.sightings_for_node(node_id),
        history=store.history_for(sorted(history_ids)),
    )


@app.get("/api/related", response_model=RelatedResponse)
def get_related(a: str, b: str) -> RelatedResponse:
    """How two nodes relate on each axis, with a ready-to-show sentence."""
    node_a, node_b = store.get_node(a), store.get_node(b)
    if node_a is None or node_b is None:
        raise HTTPException(404, "Unknown node.")
    links = store.all_links()
    character = graph.common_ancestor(links, a, b, "character")
    fmt = graph.common_ancestor(links, a, b, "format")
    node_ids = {a, b}
    for path in (character, fmt):
        if path is not None:
            node_ids |= {*path.path_a, *path.path_b}
    nodes_by_id = {n.id: n for n in store.get_nodes(sorted(node_ids))}
    character_node = nodes_by_id.get(character.ancestor_id) if character else None
    format_node = nodes_by_id.get(fmt.ancestor_id) if fmt else None
    sentence = graph.related_sentence(node_a, node_b, character_node, format_node)
    return RelatedResponse(
        a_id=a,
        b_id=b,
        nodes=list(nodes_by_id.values()),
        character=character,
        format=fmt,
        sentence=sentence,
    )


@app.get("/api/week", response_model=WeekResponse)
def get_week() -> WeekResponse:
    """Rising families and newly detected specimens."""
    return WeekResponse(rising=store.rising(), new_specimens=store.new_specimens())


@app.get("/api/health")
def get_health() -> dict[str, Any]:
    """Not in the contract; a quick deploy check."""
    return {"ok": True, **store.counts()}
