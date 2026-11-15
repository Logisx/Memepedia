"""The live loop: fetch fresh posts, label them, resolve them to a family, and save sightings.

One tick covers one feed end to end (FETCH, LOOK, RESOLVE). `tick_all` runs every feed plus
emerging-meme detection and specimen expiry. `identify` serves a dropped image; `authentic` and
`handle_webhook` serve the Context.dev monitor webhook. In production every scheduled tick goes
through `guarded_tick` (cost guards, a per-feed throttle, then `maintenance`), reached either from
a monitor webhook or, as the fallback when no webhook has arrived lately, from `clock_tick`.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from memepedia import budget, contextdev, db, dedupe, imageprep, resolver, sources, store
from memepedia import llm as llm_module
from memepedia.config import Settings, get_settings
from memepedia.llm import Cluster, PendingItem, RootInfo
from memepedia.models import IdentifyResponse, Post, SightingState, VisionLabel
from memepedia.sources import FEEDS, Feed, SourceError
from memepedia.sources import lemmy as lemmy_source
from memepedia.sources import reddit as reddit_source

log = logging.getLogger("memepedia.live")

_MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # a dropped image (identify)
_MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024  # a post's image; shrunk before the vision call
_IMAGE_TIMEOUT_S = 15.0
_USER_AGENT = "memepedia-archive/0.1 (hackathon research project)"
_AUTO_TRACE_MIN_CONFIDENCE = 0.85
_PENDING_WINDOW_HOURS = 72
_PENDING_MAX = 60
_PENDING_MIN_CLUSTER = 3
_TICK_MIN_INTERVAL_S = 300
_MAINTENANCE_EVERY_S = 15 * 60
_AUTO_PAUSE_EVERY_S = 30 * 60
_FALLBACK_MINUTES = 20.0
HEARTBEAT_KEY = "last_webhook"

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
    duplicates: int = 0  # reposts of a sighting already in the archive: saved, never looked at


@dataclass(frozen=True)
class Member:
    """One sighting in a proposed cluster, reduced to what `qualifies` needs to judge it."""

    sighting_id: str
    author: str | None
    image_url: str
    overlaid_text: str | None


@dataclass(frozen=True)
class _Looked:
    """What the LOOK step produced for one post: a label, an unclassified miss, or an error.

    `error` is a failed vision call (the post is not saved, so the next tick retries it);
    `look_error` is why the image itself could not be read (saved as unclassified).
    """

    post: Post
    vision: VisionLabel | None
    error: str | None
    look_error: str | None = None
    fingerprint: str | None = None


@dataclass(frozen=True)
class Fetched:
    """One post's image ready for the vision model, or why it could not be read."""

    prepared: imageprep.Prepared | None
    error: str | None


def download_image(url: str) -> tuple[bytes, None] | tuple[None, str]:
    """Downloads one image: its bytes, or why not; never raises.

    The reason is one of "http_<status>", "network", "unsupported:<mime>" or "too_large".
    """
    chunks: list[bytes] = []
    try:
        with (
            httpx.Client(
                follow_redirects=True,
                timeout=_IMAGE_TIMEOUT_S,
                headers={"User-Agent": _USER_AGENT},
            ) as client,
            client.stream("GET", url) as resp,
        ):
            if resp.status_code != 200:
                return None, f"http_{resp.status_code}"
            mime = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if mime and mime not in imageprep.INPUT_MIME and mime != "application/octet-stream":
                return None, f"unsupported:{mime}"
            declared = resp.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > _MAX_DOWNLOAD_BYTES:
                return None, "too_large"
            size = 0
            for chunk in resp.iter_bytes():
                size += len(chunk)
                if size > _MAX_DOWNLOAD_BYTES:
                    return None, "too_large"
                chunks.append(chunk)
    except httpx.HTTPError:
        return None, "network"
    return b"".join(chunks), None


def readable_image_url(url: str) -> str:
    """Where an image stored before the source fixes can actually be fetched from: the
    full-size Reddit image for a preview thumbnail, the real image behind a Lemmy proxy link."""
    return lemmy_source.unwrap_proxy(reddit_source.full_image_url(url))


def fetch_image(url: str) -> Fetched:
    """Downloads and decodes one post's image (any of `imageprep.INPUT_MIME`); never raises."""
    raw, error = download_image(url)
    if raw is None:
        return Fetched(None, error)
    try:
        return Fetched(imageprep.prepare(raw), None)
    except imageprep.ImageError:
        return Fetched(None, "undecodable")


def _archive_context() -> tuple[list[RootInfo], list[str]]:
    """The root list and known names every vision call is given."""
    roots = [RootInfo(n.id, n.name, n.summary or "") for n in store.root_nodes()]
    names = [n.name for n in store.all_nodes()]
    return roots, names


def _guardrail(image: bytes, mime: str, label: VisionLabel) -> VisionLabel:
    """`label` with its nsfw verdict replaced by the guardrail model's (GUARDRAIL_MODEL).

    A label that already stands for a safety block stays as it is (no second call). When the
    guardrail call fails or its answer is unreadable, the labelling model's own verdict is kept.
    """
    if llm_module.was_blocked(label):
        return label
    try:
        nsfw, reason = llm_module.label_nsfw_only(image, mime)
    except llm_module.LLMError as exc:
        log.warning("nsfw guardrail failed, keeping the labeller's verdict: %s", exc)
        return label
    return label.model_copy(update={"nsfw": nsfw, "nsfw_reason": reason})


def _look_one(
    post: Post, fetched: Fetched, roots: Sequence[RootInfo], known_names: Sequence[str]
) -> _Looked:
    """Labels one fetched image, then has the guardrail judge it; never raises."""
    image = fetched.prepared
    if image is None:
        return _Looked(post, None, None, look_error=fetched.error)
    try:
        vision = llm_module.vision_label(
            image.data, image.mime, title=post.title, roots=roots, known_names=known_names
        )
    except llm_module.LLMError as exc:
        return _Looked(post, None, str(exc), fingerprint=image.fingerprint)
    vision = _guardrail(image.data, image.mime, vision)
    return _Looked(post, vision, None, fingerprint=image.fingerprint)


@dataclass(frozen=True)
class Thresholds:
    """How sure the vision model must be before a label may stamp a sighting."""

    exact: float  # the guess equals an archive name or alias
    near: float  # any other guess: a close spelling confirmed by the LLM
    subjects: bool  # whether a depicted character may stamp a post with no usable guess
    titles: bool = True  # whether a post title naming a meme outright may stamp it (last rule)

    @classmethod
    def from_settings(cls, settings: Settings) -> Thresholds:
        return cls(
            exact=settings.vision_exact_min_confidence,
            near=settings.vision_min_confidence,
            subjects=settings.match_subjects,
            titles=settings.match_titles,
        )


@dataclass(frozen=True)
class LabelMatch:
    """The node a label matched and how: its guess exactly, near, or by a depicted character."""

    node_id: str
    via: Literal["exact", "near", "subject", "title"]


def match_label(
    label: VisionLabel, t: Thresholds, m: resolver.Matcher, title: str | None = None
) -> LabelMatch | None:
    """The archive node a vision label points at, or None. The first of four rules that fits.

    An exact guess passes at the lower threshold, any other guess needs the higher one, then the
    depicted characters, and last a post `title` that names a meme outright ("POV: you're
    Jensen Huang"), for a meme only. Confidence belongs to the template guess only, so the
    subject and title rules ignore it.
    """
    guess = label.template_guess
    if guess and label.confidence >= t.exact and (node_id := m.exact(guess)) is not None:
        return LabelMatch(node_id, "exact")
    if guess and label.confidence >= t.near and (node_id := m.near(guess, label.description)):
        return LabelMatch(node_id, "near")
    if t.subjects and (node_id := m.subject(label.subjects)) is not None:
        return LabelMatch(node_id, "subject")
    if t.titles and title and label.is_meme and (node_id := m.title(title)) is not None:
        return LabelMatch(node_id, "title")
    return None


def classify(
    label: VisionLabel, t: Thresholds, m: resolver.Matcher, title: str | None = None
) -> tuple[str | None, SightingState]:
    """Decides a sighting's node and state from its vision label (and the post title);
    never stamps a weak guess."""
    if not label.is_meme:
        return None, "unclassified"
    match = match_label(label, t, m, title)
    if match is not None:
        return match.node_id, "resolved"
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
    looked: Sequence[_Looked], thresholds: Thresholds, matcher: resolver.Matcher, errors: list[str]
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
            else classify(result.vision, thresholds, matcher, result.post.title)
        )
        sid = store.insert_sighting(
            result.post,
            result.vision,
            node_id,
            state,
            look_error=result.look_error,
            fingerprint=result.fingerprint,
        )
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


def _trace_turn_refused() -> str | None:
    """Count one background trace against its cap, or say (and log) why the cap refuses it."""
    reason = budget.block_reason("traces", background=True)
    if reason is not None:
        log.warning("background trace skipped: %s", reason)
        return f"background trace skipped: {reason}"
    budget.charge("traces", 1)
    return None


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
        if (refused := _trace_turn_refused()) is not None:
            errors.append(refused)
            break
        try:
            node_id = trace.run(guess, as_specimen=True)
        except Exception as exc:  # trace.run should not raise; guard the tick anyway
            errors.append(f"auto-trace {guess!r}: {exc}")
            continue
        if node_id is not None:
            store.attach_sightings([sid], node_id)
            traced.append(node_id)
    return traced


@dataclass(frozen=True)
class _Repeat:
    """A post in this batch that repeats another sighting (`memepedia.dedupe`)."""

    post: Post
    fetched: Fetched
    original_id: str


def _candidate(post: Post, fetched: Fetched) -> dedupe.Candidate:
    fingerprint = fetched.prepared.fingerprint if fetched.prepared else None
    return dedupe.Candidate(
        store.sighting_id(post.post_url),
        post.image_url,
        fingerprint,
        post.author,
        post.title,
        post.posted_at,
    )


def _split_repeats(
    batch: Sequence[Post], fetched: Sequence[Fetched]
) -> tuple[list[tuple[Post, Fetched]], list[_Repeat]]:
    """Splits a fetched batch into posts to look at and reposts of something already seen.

    A post is compared with the archive's recent sightings (`store.dedupe_candidates`), every
    earlier sighting of its exact image URL, and the posts before it in this same batch, so two
    copies arriving together cost one vision call. The batch is walked oldest first, so the
    first post of a picture is the one kept; the posts to look at keep the batch's own order.
    """
    rows = store.dedupe_candidates() + store.sightings_with_image([p.image_url for p in batch])
    seen = list({row["id"]: dedupe.candidate(row) for row in rows}.values())
    pairs = list(zip(batch, fetched, strict=True))
    repeat_of: dict[int, str] = {}
    for index in sorted(range(len(pairs)), key=lambda i: pairs[i][0].posted_at):
        post, image = pairs[index]
        candidate = _candidate(post, image)
        match = dedupe.find_original(candidate, seen)
        if match is None:
            seen.append(candidate)
        else:
            repeat_of[index] = match.original.id
    fresh = [pair for i, pair in enumerate(pairs) if i not in repeat_of]
    repeats = [_Repeat(*pairs[i], original_id) for i, original_id in repeat_of.items()]
    return fresh, repeats


def _save_repeats(repeats: Sequence[_Repeat]) -> int:
    """Saves each repost with its original's stamp; one whose original is not saved yet (its
    vision call failed this tick) is left for the next tick. Returns how many were saved."""
    saved = 0
    for repeat in repeats:
        original = store.sighting_row(repeat.original_id)
        if original is None:
            continue
        vision = llm_module.parse_stored_vision(original["vision"]) if original["vision"] else None
        if vision is not None and original["nsfw"] is not None:
            vision = vision.model_copy(update={"nsfw": original["nsfw"]})
        image = repeat.fetched.prepared
        sid = store.insert_sighting(
            repeat.post,
            vision,
            original["node_id"],
            original["state"],
            nsfw=original["nsfw"],
            look_error=repeat.fetched.error,
            fingerprint=image.fingerprint if image else None,
            duplicate_of=repeat.original_id,
        )
        saved += sid is not None
    return saved


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
        # FETCH every image, DEDUPE against what is already known, LOOK only at the rest.
        fetched = list(pool.map(lambda post: fetch_image(post.image_url), batch))
        to_look, repeats = _split_repeats(batch, fetched)
        futures = [
            pool.submit(_look_one, post, image, roots, known_names) for post, image in to_look
        ]
        looked = [f.result() for f in futures]

    resolved, pending, unclassified, candidates = _save_looked(
        looked, Thresholds.from_settings(settings), resolver.Matcher.from_store(), errors
    )
    duplicates = _save_repeats(repeats)
    traced = _auto_trace(candidates, settings.auto_traces_per_tick, errors)
    return TickReport(
        feed=feed_key,
        fetched=fetched_count,
        fresh=fresh_count,
        looked=len(to_look),
        resolved=resolved,
        pending=pending,
        unclassified=unclassified,
        traced=traced,
        errors=errors,
        duplicates=duplicates,
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
    if _trace_turn_refused() is not None:
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
    if mime_type not in imageprep.INPUT_MIME:
        raise ValueError(f"unsupported image type: {mime_type!r}")
    if len(image) > _MAX_UPLOAD_BYTES:
        raise ValueError("image is larger than the 5 MB limit")
    try:
        prepared = imageprep.prepare(image)
    except imageprep.ImageError as exc:
        raise ValueError("that file could not be read as an image") from exc
    roots, known_names = _archive_context()
    label = llm_module.vision_label(
        prepared.data, prepared.mime, title=None, roots=roots, known_names=known_names
    )
    label = _guardrail(prepared.data, prepared.mime, label)
    if label.nsfw:
        return IdentifyResponse(node_id=None, trace_query=None, guess=None, overlaid_text=None)
    match = match_label(
        label, Thresholds.from_settings(get_settings()), resolver.Matcher.from_store()
    )
    node_id = match.node_id if match else None
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


def webhook_secrets(payload: Mapping[str, Any]) -> list[str]:
    """The secrets a delivery may be signed with: its own monitor's, then CONTEXTDEV_WEBHOOK_SECRET.

    Context.dev issues one secret per monitor, which `scripts/monitors.py create` stores in
    `webhook_monitors`. The payload is read before it is trusted only to find which secret to try.
    """
    secrets: list[str] = []
    monitor_id = _monitor_id_from_payload(payload)
    row = store.monitor_row(monitor_id) if monitor_id else None
    if row is not None and row[1]:
        secrets.append(row[1])
    env_secret = get_settings().webhook_secret
    if env_secret:
        secrets.append(env_secret)
    return secrets


def authentic(raw_body: bytes, header: str, payload: Mapping[str, Any]) -> bool:
    """Whether a delivery is signed with a secret this archive holds; with none held, nothing is."""
    return any(verify_signature(raw_body, header, s) for s in webhook_secrets(payload))


def _run_credits(payload: Mapping[str, Any]) -> float:
    """Credits the delivered monitor run cost (a page run is 1); 0 for a skipped run."""
    run = (payload.get("data") or {}).get("run")
    if not isinstance(run, Mapping):
        return 0.0
    default = 1 if run.get("status") in {"completed", "failed"} else 0
    try:
        return float(run.get("credits_charged", default) or 0)
    except (TypeError, ValueError):
        return float(default)


def _page_changed(payload: Mapping[str, Any]) -> bool:
    """Whether the delivered run found the watched page changed (null `change` when not)."""
    return (payload.get("data") or {}).get("change") is not None


def _feed_for_monitor(monitor_id: str) -> str | None:
    """The feed a monitor watches: from `webhook_monitors`, else from its name on Context.dev."""
    row = store.monitor_row(monitor_id)
    if row is not None:
        return row[0]
    if monitor_id not in _monitor_feed_cache:
        _refresh_monitor_cache()
    return _monitor_feed_cache.get(monitor_id)


def handle_webhook(payload: Mapping[str, Any]) -> str | None:
    """Counts one authenticated monitor run, then ticks its feed if the watched page changed.

    Every delivery refreshes the heartbeat the Modal clock checks before standing in. Returns
    the feed key that was ticked, or None (unknown monitor, no change, or a guard said no).
    """
    monitor_id = _monitor_id_from_payload(payload)
    if monitor_id is None:
        return None
    store.set_state(HEARTBEAT_KEY, monitor_id)
    budget.charge("contextdev", _run_credits(payload))
    feed_key = _feed_for_monitor(monitor_id)
    if feed_key is None or not _page_changed(payload):
        return None
    return feed_key if guarded_tick(feed_key) is not None else None


def _pause_monitors_once() -> None:
    """Pause every monitor this archive created (each run costs a credit); every 30 min at most."""
    if not budget.claim("auto_pause", _AUTO_PAUSE_EVERY_S):
        return
    for monitor_id in store.monitor_ids():
        try:
            contextdev.set_monitor_status(monitor_id, "paused")
        except contextdev.ContextDevError as exc:
            log.warning("could not pause monitor %s: %s", monitor_id, exc)


def maintenance() -> None:
    """At most every 15 minutes: turn qualifying pending clusters into specimens, expire stale."""
    if not budget.claim("maintenance", _MAINTENANCE_EVERY_S):
        return
    try:
        detect_specimens()
        store.expire_specimens()
    except Exception:  # background housekeeping must never break the tick that called it
        log.exception("maintenance failed")


def _guarded_tick(feed_key: str) -> TickReport | None:
    reason = budget.background_block()
    if reason is not None:
        log.warning("paid work stopped, %s not ticked: %s", feed_key, reason)
        _pause_monitors_once()
        return None
    if not budget.claim(f"tick:{feed_key}", _TICK_MIN_INTERVAL_S):
        log.info("%s was ticked less than %ss ago; skipped", feed_key, _TICK_MIN_INTERVAL_S)
        return None
    report = tick(feed_key)
    log.info("%s", report)
    maintenance()
    return report


def guarded_tick(feed_key: str) -> TickReport | None:
    """Ticks one feed unless a cost guard or the per-feed throttle says no; never raises.

    Both the webhook and the Modal clock come through here, so a feed is ticked at most once per
    `_TICK_MIN_INTERVAL_S` whoever asks, and nothing is spent once a background cap is reached
    (the monitors are then paused too, since each of their runs costs a credit).
    """
    try:
        return _guarded_tick(feed_key)
    except Exception:  # a guard that cannot reach the database must not crash the caller
        log.exception("guarded_tick(%s) failed", feed_key)
        return None


def _fallback_minutes() -> float:
    get_settings()  # loads the repo's .env into the environment, once
    return float(os.environ.get("MEMEPEDIA_CLOCK_FALLBACK_MINUTES") or _FALLBACK_MINUTES)


def clock_tick(feed_key: str) -> str:
    """The Modal clock's turn: idle while monitor webhooks keep arriving, the live loop otherwise.

    With no monitor delivery in the last MEMEPEDIA_CLOCK_FALLBACK_MINUTES (default 20), and so
    also when no monitor exists, the clock ticks `feed_key` itself, through the same guards.
    """
    age = store.state_age(HEARTBEAT_KEY)
    if age is not None and age < _fallback_minutes() * 60:
        return f"idle: a monitor webhook arrived {age:.0f}s ago"
    report = guarded_tick(feed_key)
    return str(report) if report is not None else f"skipped {feed_key} (see the log)"


def feed_page_url(feed: Feed) -> str:
    """The public page a Context.dev monitor should watch for this feed."""
    if feed.platform == "lemmy":
        instance, community = feed.target.split("/", 1)
        return f"https://{instance}/c/{community}?dataType=Post&sort=New"
    if feed.platform == "reddit":
        return f"https://www.reddit.com/r/{feed.target}/new/.rss"
    if feed.platform == "imgflip":
        return f"https://imgflip.com/m/{feed.target}?sort=latest"
    raise ValueError(f"no page URL for platform {feed.platform!r}")
