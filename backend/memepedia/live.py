"""The live loop: fetch fresh posts, label them, resolve them to a family, and save sightings.

One tick covers one feed end to end (FETCH, LOOK, RESOLVE). `tick_all` runs every feed plus
emerging-meme detection and specimen expiry. `identify` serves a dropped image; `handle_webhook`
and `verify_signature` serve the Context.dev monitor webhook.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from memepedia import contextdev, db, resolver, sources, store
from memepedia import llm as llm_module
from memepedia.config import get_settings
from memepedia.llm import Cluster, PendingItem, RootInfo
from memepedia.models import IdentifyResponse, Post, SightingState, VisionLabel
from memepedia.sources import FEEDS, Feed, SourceError

log = logging.getLogger("memepedia.live")

_ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024
_IMAGE_TIMEOUT_S = 15.0
_USER_AGENT = "memepedia-archive/0.1 (hackathon research project)"
_AUTO_TRACE_MIN_CONFIDENCE = 0.85
_PENDING_WINDOW_HOURS = 72
_PENDING_MAX = 60
_PENDING_MIN_CLUSTER = 3

Shared = Literal["image", "structure", "phrase"]

_last_pending_ids: set[str] | None = None
_monitor_feed_cache: dict[str, str] = {}


@dataclass(frozen=True)
class TickReport:
    """What happened when one feed was ticked."""

    feed: str
    fetched: int
    fresh: int
    looked: int
    resolved: int
    pending: int
    unclassified: int
    traced: list[str]
    errors: list[str]


@dataclass(frozen=True)
class Member:
    """One sighting in a proposed cluster, reduced to what `qualifies` needs to judge it."""

    sighting_id: str
    author: str | None
    image_url: str
    overlaid_text: str | None


@dataclass(frozen=True)
class _Looked:
    """What the LOOK step produced for one post: a label, an unclassified miss, or an error."""

    post: Post
    vision: VisionLabel | None
    error: str | None


def _download_image(url: str) -> tuple[bytes, str] | None:
    """Downloads one post's image; None when it cannot be fetched or is not a supported type."""
    try:
        with httpx.Client(
            follow_redirects=True, timeout=_IMAGE_TIMEOUT_S, headers={"User-Agent": _USER_AGENT}
        ) as client:
            resp = client.get(url)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    mime = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if mime not in _ALLOWED_MIME or len(resp.content) > _MAX_IMAGE_BYTES:
        return None
    return resp.content, mime


def _archive_context() -> tuple[list[RootInfo], list[str]]:
    """The root list and known names every vision call is given."""
    roots = [RootInfo(n.id, n.name, n.summary or "") for n in store.root_nodes()]
    names = [n.name for n in store.all_nodes()]
    return roots, names


def _look_one(post: Post, roots: Sequence[RootInfo], known_names: Sequence[str]) -> _Looked:
    """Downloads one post's image and labels it; never raises."""
    downloaded = _download_image(post.image_url)
    if downloaded is None:
        return _Looked(post, None, None)
    data, mime = downloaded
    try:
        vision = llm_module.vision_label(
            data, mime, title=post.title, roots=roots, known_names=known_names
        )
    except llm_module.LLMError as exc:
        return _Looked(post, None, str(exc))
    return _Looked(post, vision, None)


def _resolve(name: str, hint: str | None) -> str | None:
    return resolver.resolve(name, hint=hint)


def classify(
    label: VisionLabel,
    min_confidence: float,
    resolve: Callable[[str, str | None], str | None],
) -> tuple[str | None, SightingState]:
    """Decides a sighting's node and state from its vision label; never stamps a weak guess."""
    if not label.is_meme:
        return None, "unclassified"
    if label.template_guess and label.confidence >= min_confidence:
        node_id = resolve(label.template_guess, label.description)
        if node_id is not None:
            return node_id, "resolved"
    return None, "pending"


def _fresh_batch(feed: Feed, cap: int) -> tuple[list[Post], int, int]:
    """This feed's unknown posts, newest first, capped at `cap`; also the fetched/fresh counts."""
    posts = sources.fetch(feed)
    known = store.known_post_urls([p.post_url for p in posts])
    fresh = sorted(
        (p for p in posts if p.post_url not in known), key=lambda p: p.posted_at, reverse=True
    )
    return fresh[:cap], len(posts), len(fresh)


def _save_looked(
    looked: Sequence[_Looked], min_confidence: float, errors: list[str]
) -> tuple[int, int, int, list[tuple[str, str]]]:
    """Classifies and saves each LOOK result; returns counts and auto-trace candidate pairs."""
    resolved = pending = unclassified = 0
    candidates: list[tuple[str, str]] = []
    for result in looked:
        if result.error is not None:
            errors.append(f"{result.post.post_url}: {result.error}")
            continue
        node_id, state = (
            (None, "unclassified")
            if result.vision is None
            else classify(result.vision, min_confidence, _resolve)
        )
        sid = store.insert_sighting(result.post, result.vision, node_id, state)
        if sid is None:
            continue
        if state == "resolved":
            resolved += 1
        elif state == "pending":
            pending += 1
            guess = result.vision.template_guess if result.vision else None
            if guess and result.vision and result.vision.confidence >= _AUTO_TRACE_MIN_CONFIDENCE:
                candidates.append((sid, guess))
        else:
            unclassified += 1
    return resolved, pending, unclassified, candidates


def _has_second_sighting(guess: str, pending_rows: Sequence[db.Row]) -> bool:
    """Whether `guess`'s template was also seen, within the window, from another author.

    Counts distinct authors among pending rows whose own template guess normalises to the
    same name as `guess` (the resolver's own normalisation, so aliasing and casing match);
    a missing author counts as one author regardless of how many anonymous rows there are.
    """
    key = resolver.normalize(guess)
    named_authors: set[str] = set()
    anon = False
    for row in pending_rows:
        vision = row.get("vision") or {}
        template_guess = vision.get("template_guess")
        if not template_guess or resolver.normalize(template_guess) != key:
            continue
        author = row.get("author")
        if author is None:
            anon = True
        else:
            named_authors.add(author)
    return len(named_authors) + (1 if anon else 0) >= 2


def _auto_trace(candidates: Sequence[tuple[str, str]], cap: int, errors: list[str]) -> list[str]:
    """Traces, as specimens, up to `cap` pending candidates seen from a second author."""
    from memepedia import trace

    if not candidates:
        return []
    pending_rows = store.pending_sightings(hours=_PENDING_WINDOW_HOURS)
    qualifying = [
        (sid, guess) for sid, guess in candidates if _has_second_sighting(guess, pending_rows)
    ][:cap]
    traced: list[str] = []
    for sid, guess in qualifying:
        try:
            node_id = trace.run(guess, as_specimen=True)
        except Exception as exc:  # trace.run should not raise; guard the tick anyway
            errors.append(f"auto-trace {guess!r}: {exc}")
            continue
        if node_id is not None:
            store.attach_sightings([sid], node_id)
            traced.append(node_id)
    return traced


def _tick(feed_key: str) -> TickReport:
    errors: list[str] = []
    feed = next((f for f in FEEDS if f.key == feed_key), None)
    if feed is None:
        return TickReport(feed_key, 0, 0, 0, 0, 0, 0, [], [f"unknown feed {feed_key!r}"])
    settings = get_settings()
    try:
        batch, fetched_count, fresh_count = _fresh_batch(feed, settings.vision_per_tick)
    except SourceError as exc:
        return TickReport(feed_key, 0, 0, 0, 0, 0, 0, [], [str(exc)])

    roots, known_names = _archive_context()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_look_one, post, roots, known_names) for post in batch]
        looked = [f.result() for f in futures]

    resolved, pending, unclassified, candidates = _save_looked(
        looked, settings.vision_min_confidence, errors
    )
    traced = _auto_trace(candidates, settings.auto_traces_per_tick, errors)
    return TickReport(
        feed=feed_key,
        fetched=fetched_count,
        fresh=fresh_count,
        looked=len(batch),
        resolved=resolved,
        pending=pending,
        unclassified=unclassified,
        traced=traced,
        errors=errors,
    )


def tick(feed_key: str) -> TickReport:
    """Fetches, looks at, resolves and saves one feed's freshest posts; never raises."""
    try:
        return _tick(feed_key)
    except Exception as exc:  # a tick must never raise; the caller just gets an error
        log.exception("tick(%s) failed unexpectedly", feed_key)
        return TickReport(feed_key, 0, 0, 0, 0, 0, 0, [], [str(exc)])


def tick_all() -> list[TickReport]:
    """Ticks every feed once, then detects emerging specimens and expires stale ones."""
    reports = [tick(feed.key) for feed in FEEDS]
    detect_specimens()
    store.expire_specimens()
    return reports


def qualifies(members: Sequence[Member], shared: Shared) -> bool:
    """The numeric rule for a cluster to become a new specimen."""
    if len(members) < _PENDING_MIN_CLUSTER:
        return False
    named_authors = {m.author for m in members if m.author is not None}
    anon = any(m.author is None for m in members)
    if len(named_authors) + (1 if anon else 0) < 2:
        return False
    if shared == "phrase":
        return len({m.image_url for m in members}) > 1
    return len({m.overlaid_text for m in members}) > 1


def _pending_item(row: db.Row) -> PendingItem:
    vision = row.get("vision") or {}
    return PendingItem(
        sighting_id=row["id"],
        title=row.get("title"),
        author=row.get("author"),
        description=str(vision.get("description") or ""),
        structure_class=vision.get("structure_class"),
        overlaid_text=vision.get("overlaid_text"),
        catchphrase=vision.get("catchphrase"),
        subjects=tuple(vision.get("subjects") or ()),
    )


def _members_for(cluster: Cluster, row_by_id: Mapping[str, db.Row]) -> list[Member]:
    members = []
    for sid in cluster.sighting_ids:
        row = row_by_id.get(sid)
        if row is None:
            continue
        vision = row.get("vision") or {}
        members.append(
            Member(sid, row.get("author"), row["image_url"], vision.get("overlaid_text"))
        )
    return members


def _cluster_context(cluster: Cluster, row_by_id: Mapping[str, db.Row]) -> str:
    lines = [cluster.summary]
    for sid in cluster.sighting_ids:
        row = row_by_id.get(sid)
        if row is None:
            continue
        vision = row.get("vision") or {}
        lines.append(
            f"- {vision.get('description') or ''} (text: {vision.get('overlaid_text') or 'none'})"
        )
    return "\n".join(lines)


def _earliest_image(cluster: Cluster, row_by_id: Mapping[str, db.Row]) -> tuple[str, str] | None:
    rows = [row_by_id[sid] for sid in cluster.sighting_ids if sid in row_by_id]
    if not rows:
        return None
    earliest = min(rows, key=lambda r: r["posted_at"])
    return earliest["image_url"], earliest["post_url"]


def _specimen_message(cluster: Cluster, members: Sequence[Member]) -> str:
    named_authors = {m.author for m in members if m.author is not None}
    anon = any(m.author is None for m in members)
    author_count = len(named_authors) + (1 if anon else 0)
    tail = "different images" if cluster.shared == "phrase" else "different captions"
    return (
        f"Noticed {len(members)} posts from {author_count} authors sharing the same "
        f"{cluster.shared} with {tail}."
    )


def _apply_cluster(cluster: Cluster, row_by_id: Mapping[str, db.Row]) -> str | None:
    from memepedia import trace

    members = _members_for(cluster, row_by_id)
    if not qualifies(members, cluster.shared):
        return None
    context = _cluster_context(cluster, row_by_id)
    node_id = trace.run(cluster.name, context=context, as_specimen=True)
    if node_id is None:
        return None
    store.attach_sightings([m.sighting_id for m in members], node_id)
    node = store.get_node(node_id)
    if node is None:
        return node_id
    if node.image_url is None:
        image = _earliest_image(cluster, row_by_id)
        if image is not None:
            store.set_node_image(node_id, image[0], image[1])
    if node.status == "specimen":
        store.add_history("specimen", node_id, _specimen_message(cluster, members))
    return node_id


def detect_specimens() -> list[str]:
    """Clusters recent pending sightings and traces any cluster that qualifies as a specimen."""
    global _last_pending_ids
    rows = store.pending_sightings(hours=_PENDING_WINDOW_HOURS)[-_PENDING_MAX:]
    current_ids = {r["id"] for r in rows}
    if len(current_ids) < _PENDING_MIN_CLUSTER or current_ids == _last_pending_ids:
        _last_pending_ids = current_ids
        return []
    _last_pending_ids = current_ids
    row_by_id = {r["id"]: r for r in rows}
    clusters = llm_module.cluster_pending([_pending_item(r) for r in rows])
    attached = [_apply_cluster(c, row_by_id) for c in clusters]
    return [node_id for node_id in attached if node_id is not None]


def identify(image: bytes, mime_type: str) -> IdentifyResponse:
    """Labels a dropped image and either resolves it or hands back a trace query."""
    if mime_type not in _ALLOWED_MIME:
        raise ValueError(f"unsupported image type: {mime_type!r}")
    if len(image) > _MAX_IMAGE_BYTES:
        raise ValueError("image is larger than the 5 MB limit")
    roots, known_names = _archive_context()
    label = llm_module.vision_label(
        image, mime_type, title=None, roots=roots, known_names=known_names
    )
    if label.nsfw:
        return IdentifyResponse(node_id=None, trace_query=None, guess=None, overlaid_text=None)
    node_id = None
    settings = get_settings()
    if label.template_guess and label.confidence >= settings.vision_min_confidence:
        node_id = resolver.resolve(label.template_guess, hint=label.description)
    guess = label.template_guess or label.description or None
    trace_query = None if node_id is not None else guess
    return IdentifyResponse(
        node_id=node_id, trace_query=trace_query, guess=guess, overlaid_text=label.overlaid_text
    )


def verify_signature(
    raw_body: bytes, header: str, secret: str, *, tolerance_s: int = 300, now: float | None = None
) -> bool:
    """Checks a Context.dev `X-Context-Signature: t=<unix>,v1=<hmac>` header, constant-time."""
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    ts_raw, signature = parts.get("t"), parts.get("v1")
    if ts_raw is None or signature is None or not ts_raw.lstrip("-").isdigit():
        return False
    ts = int(ts_raw)
    if abs((now if now is not None else time.time()) - ts) > tolerance_s:
        return False
    expected = hmac.new(
        secret.encode(), f"{ts_raw}.".encode() + raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _monitor_id_from_payload(payload: Mapping[str, Any]) -> str | None:
    data = payload.get("data") or {}
    run = data.get("run") or {}
    change = data.get("change") or {}
    monitor_id = run.get("monitor_id") or change.get("monitor_id") or payload.get("monitor_id")
    return str(monitor_id) if monitor_id else None


def _refresh_monitor_cache() -> None:
    global _monitor_feed_cache
    cache: dict[str, str] = {}
    for monitor in contextdev.list_monitors():
        name = str(monitor.get("name") or "")
        monitor_id = monitor.get("id")
        if name.startswith("memepedia:") and monitor_id:
            cache[str(monitor_id)] = name.removeprefix("memepedia:")
    _monitor_feed_cache = cache


def handle_webhook(payload: Mapping[str, Any]) -> str | None:
    """Runs a tick for the feed a Context.dev webhook delivery names, or None if unrecognised."""
    monitor_id = _monitor_id_from_payload(payload)
    if monitor_id is None:
        return None
    if monitor_id not in _monitor_feed_cache:
        _refresh_monitor_cache()
    feed_key = _monitor_feed_cache.get(monitor_id)
    if feed_key is None:
        return None
    tick(feed_key)
    return feed_key


def feed_page_url(feed: Feed) -> str:
    """The public page a Context.dev monitor should watch for this feed."""
    if feed.platform == "lemmy":
        instance, community = feed.target.split("/", 1)
        return f"https://{instance}/c/{community}?dataType=Post&sort=New"
    if feed.platform == "reddit":
        return f"https://www.reddit.com/r/{feed.target}/new/"
    if feed.platform == "imgflip":
        return f"https://imgflip.com/m/{feed.target}?sort=latest"
    raise ValueError(f"no page URL for platform {feed.platform!r}")
