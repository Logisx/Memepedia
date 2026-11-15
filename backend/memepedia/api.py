"""The public Memepedia API: the contract's routes plus the Context.dev webhook."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import deque
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from memepedia import budget, db, graph, live, resolver, static, store, trace
from memepedia.config import get_settings
from memepedia.llm import LLMError
from memepedia.models import (
    Descent,
    IdentifyResponse,
    Kind,
    Link,
    MemeNode,
    NodesResponse,
    ProposalRequest,
    ProposalResponse,
    RandomResponse,
    RelatedResponse,
    Sighting,
    TraceEvent,
    TraceRequest,
    TreeResponse,
    WallResponse,
    WeekResponse,
)
from memepedia.sources import FEEDS

log = logging.getLogger("memepedia.api")

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_WEBHOOK_BYTES = 2 * 1024 * 1024


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    if not get_settings().read_only:
        db.init_schema()
    yield


app = FastAPI(title="Memepedia API", lifespan=_lifespan)

# MEMEPEDIA_READ_ONLY (the frozen staging copy): every API route that is not a read answers 503,
# so the copy can never trace, call Gemini or Context.dev, or write. Added before CORS so the
# refusal still carries CORS headers.
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
READ_ONLY_MESSAGE = "This is a read-only backup copy of Memepedia: tracing and uploads are off."


@app.middleware("http")
async def _refuse_writes_when_read_only(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    writing = request.method not in _READ_METHODS and request.url.path.startswith("/api/")
    if writing and get_settings().read_only:
        return _error(READ_ONLY_MESSAGE, 503)
    return await call_next(request)


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


MAX_WALL_PAGE_LIMIT = 100


@app.get("/api/wall", response_model=WallResponse)
def get_wall(
    since: str | None = None,
    before: str | None = None,
    limit: int = 60,
    sensitive: bool = False,
) -> WallResponse:
    """Recent sightings; pass back server_time as `since` on the next poll.

    `before` pages backwards through older sightings: pass the previous response's
    `next_before` to get the page just older than it (null once the wall is exhausted).
    `limit` is capped at 100 when `before` is used.
    `sensitive=true` includes nsfw (true or unlabelled) sightings too, for a viewer who
    asked to see them; the default omits them, as before.
    """
    since_dt = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError as exc:
            raise HTTPException(400, "Invalid 'since' timestamp.") from exc
    before_cursor = None
    if before is not None:
        try:
            before_cursor = store.decode_wall_cursor(before)
        except ValueError as exc:
            raise HTTPException(400, "Invalid 'before' cursor.") from exc
        limit = min(limit, MAX_WALL_PAGE_LIMIT)
    sightings, cursor, next_before = store.wall_page(
        since_dt, limit, include_sensitive=sensitive, before=before_cursor
    )
    return WallResponse(
        sightings=sightings, server_time=cursor, sources_watched=len(FEEDS), next_before=next_before
    )


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


def _variant(sighting: Sighting, vision: dict[str, Any] | None, node: MemeNode) -> str | None:
    """Which template or family a post on `node`'s page uses, when it is not `node` itself.

    A post stamped with another node is that node (its name); a post of `node` whose vision
    label guessed a different template is that guess; anything else is None.
    """
    if sighting.node_id != node.id:
        return sighting.node_name
    guess = (vision or {}).get("template_guess")
    if not guess:
        return None
    own = {resolver.normalize(name) for name in (node.name, *node.aliases)}
    return None if resolver.normalize(str(guess)) in own else str(guess)


def _tree_sightings(node: MemeNode, sensitive: bool) -> list[Sighting]:
    """The posts shown on a meme's page, each with its `variant`.

    A character's page also gets the posts where it appears inside another meme's template.
    """
    names = [node.name, *node.aliases] if node.kind == "character" else None
    rows = store.node_sightings(node.id, include_sensitive=sensitive, names=names)
    return [s.model_copy(update={"variant": _variant(s, vision, node)}) for s, vision in rows]


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
def get_tree(node_id: str, sensitive: bool = False) -> TreeResponse:
    """The family, descent chains, links, sightings and history for one node.

    `sensitive=true` includes the node's nsfw (true or unlabelled) sightings too, for a viewer
    who asked to see them; the default omits them, as before.
    """
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
        sightings=_tree_sightings(selected, sensitive),
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


class _Budget:
    """A shared allowance of calls per minute, so a looping client cannot drain paid quotas."""

    def __init__(self, limit: int, window_s: float = 60.0) -> None:
        self._limit = limit
        self._window_s = window_s
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def take(self) -> None:
        """Count one call, or refuse with a 429 when the minute's allowance is spent."""
        now = time.monotonic()
        with self._lock:
            while self._calls and now - self._calls[0] > self._window_s:
                self._calls.popleft()
            if len(self._calls) >= self._limit:
                raise HTTPException(429, "The archive is busy. Try again in a minute.")
            self._calls.append(now)


_trace_budget = _Budget(12)
_identify_budget = _Budget(20)
_proposal_budget = _Budget(12)
_webhook_budget = _Budget(120)


def _sse(events: Iterator[TraceEvent]) -> Iterator[str]:
    for event in events:
        yield f"data: {event.model_dump_json()}\n\n"


@app.post("/api/trace")
def post_trace(body: TraceRequest) -> StreamingResponse:
    """Trace a meme's lineage; the events arrive as a server-sent stream."""
    query = body.query.strip()
    if not query:
        raise HTTPException(400, "Name a meme to trace.")
    _trace_budget.take()
    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(
        _sse(trace.trace(query)), media_type="text/event-stream", headers=headers
    )


@app.post("/api/identify", response_model=IdentifyResponse)
def post_identify(image: UploadFile) -> IdentifyResponse:
    """Name the meme in an uploaded image, or say what to trace instead."""
    _identify_budget.take()
    data = image.file.read(MAX_UPLOAD_BYTES + 1)
    try:
        return live.identify(data, image.content_type or "")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(503, "The archive could not look at that image. Try again.") from exc


@app.post("/api/proposals", response_model=ProposalResponse)
def post_proposal(body: ProposalRequest) -> ProposalResponse:
    """Check a visitor's source for a sentence that supports one of the node's links."""
    _proposal_budget.take()
    try:
        return trace.propose(body.node_id, body.url.strip(), body.note.strip())
    except LookupError as exc:
        raise HTTPException(404, "Unknown node.") from exc


def _webhook_payload(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(400, "Invalid webhook body.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "Invalid webhook body.")
    return payload


def _event_id(request: Request, payload: dict[str, Any], raw: bytes) -> str:
    """The delivery's stable event id (the same across retries), else a hash of its body."""
    given = request.headers.get("X-Context-Id") or str(payload.get("id") or "")
    return given or hashlib.sha256(raw).hexdigest()


def _accept_webhook(raw: bytes, signature: str, payload: dict[str, Any], event_id: str) -> bool:
    """Refuse (401) a delivery not signed with a secret we hold; False for a repeated event."""
    if not live.authentic(raw, signature, payload):
        raise HTTPException(401, "Bad webhook signature.")
    return store.first_delivery(event_id)


@app.post("/api/webhooks/context")
async def post_context_webhook(request: Request, background: BackgroundTasks) -> dict[str, bool]:
    """A Context.dev monitor ran: check it is signed, count it once, then tick in the background.

    Unsigned or wrongly signed deliveries get a 401 whether or not any secret is configured, a
    repeated event id runs nothing, and the route takes at most `_webhook_budget` calls a minute.
    """
    raw = await request.body()
    if len(raw) > MAX_WEBHOOK_BYTES:
        raise HTTPException(413, "Webhook body too large.")
    _webhook_budget.take()
    payload = _webhook_payload(raw)
    signature = request.headers.get("X-Context-Signature", "")
    event_id = _event_id(request, payload, raw)
    if await run_in_threadpool(_accept_webhook, raw, signature, payload, event_id):
        background.add_task(live.handle_webhook, payload)
    return {"ok": True}


@app.get("/api/health")
def get_health() -> dict[str, Any]:
    """Not in the contract; a quick deploy check.

    Also says whether background work may spend now (`paid_work`) and how many seconds ago the
    last authenticated Context.dev monitor delivery arrived (`last_webhook_s`, null if never).
    """
    guards = {
        "paid_work": budget.background_block() or "allowed",
        "last_webhook_s": store.state_age(live.HEARTBEAT_KEY),
    }
    return {"ok": True, **store.counts(), **guards}


# Last, so it only answers what no API route claimed. A no-op when the web app is not built.
static.install(app, static.default_dist())
