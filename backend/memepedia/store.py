"""Every SQL query in the backend lives here; callers get back contract models."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.types.json import Json

from memepedia import db
from memepedia.models import (
    Axis,
    Evidence,
    HistoryItem,
    HistoryType,
    Kind,
    Link,
    MemeNode,
    NodeStatus,
    Post,
    RisingFamily,
    Sighting,
    SightingState,
    VisionLabel,
)

_NODE_BASE_SQL = """
SELECT n.*,
    COALESCE(c24.c, 0) AS sightings_24h,
    COALESCE(c7.c, 0) AS sightings_7d
FROM nodes n
LEFT JOIN (
    SELECT node_id, count(*) AS c FROM sightings
    WHERE posted_at >= now() - interval '24 hours' AND nsfw = false AND duplicate_of IS NULL
    GROUP BY node_id
) c24 ON c24.node_id = n.id
LEFT JOIN (
    SELECT node_id, count(*) AS c FROM sightings
    WHERE posted_at >= now() - interval '7 days' AND nsfw = false AND duplicate_of IS NULL
    GROUP BY node_id
) c7 ON c7.node_id = n.id
"""

_WALL_SELECT = (
    "SELECT s.*, n.name AS node_name FROM sightings s LEFT JOIN nodes n ON n.id = s.node_id"
)


def _row_to_node(row: db.Row) -> MemeNode:
    return MemeNode(
        id=row["id"],
        name=row["name"],
        aliases=list(row["aliases"]),
        kind=row["kind"],
        latin_name=row["latin_name"],
        image_url=row["image_url"],
        image_credit_url=row["image_credit_url"],
        first_seen=row["first_seen"],
        date_precision=row["date_precision"],
        summary=row["summary"],
        status=row["status"],
        sightings_24h=row["sightings_24h"],
        sightings_7d=row["sightings_7d"],
        nsfw=row["nsfw"],
    )


def _row_to_link(row: db.Row) -> Link:
    return Link(
        child_id=row["child_id"],
        parent_id=row["parent_id"],
        axis=row["axis"],
        status=row["status"],
        quote=row["quote"],
        source_url=row["source_url"],
        source_title=row["source_title"],
    )


def _row_to_sighting(row: db.Row) -> Sighting:
    return Sighting(
        id=row["id"],
        platform=row["platform"],
        post_url=row["post_url"],
        image_url=row["image_url"],
        title=row["title"],
        author=row["author"],
        posted_at=row["posted_at"],
        node_id=row["node_id"],
        node_name=row.get("node_name"),
        state=row["state"],
        nsfw=row["nsfw"],
        read=row.get("vision") is not None,
    )


def _row_to_history(row: db.Row) -> HistoryItem:
    return HistoryItem(
        id=str(row["id"]),
        ts=row["ts"],
        type=row["type"],
        message=row["message"],
        source_url=row["source_url"],
        pending=row["pending"],
    )


def _fetch_nodes(where_sql: str = "", params: db.Params = ()) -> list[MemeNode]:
    rows = db.fetch_all(_NODE_BASE_SQL + where_sql, params)
    return [_row_to_node(r) for r in rows]


def get_node(node_id: str) -> MemeNode | None:
    """The node with this id, or None."""
    nodes = _fetch_nodes("WHERE n.id = %s", (node_id,))
    return nodes[0] if nodes else None


def get_nodes(ids: Sequence[str]) -> list[MemeNode]:
    """Nodes for these ids, in the order given; unknown ids are skipped."""
    by_id = {n.id: n for n in _fetch_nodes("WHERE n.id = ANY(%s)", (list(ids),))}
    return [by_id[i] for i in ids if i in by_id]


def all_nodes() -> list[MemeNode]:
    """Every node in the archive."""
    return _fetch_nodes()


def _popular_mix(nodes: list[MemeNode]) -> list[MemeNode]:
    def key(node: MemeNode) -> tuple[int, int, int]:
        has_image = 0 if node.image_url else 1
        is_specimen = 0 if node.status == "established" else 1
        return (-node.sightings_7d, has_image, is_specimen)

    return sorted(nodes, key=key)


def search_nodes(q: str, limit: int = 20) -> list[MemeNode]:
    """Case-insensitive search over name and aliases; a blank q returns a popular mix."""
    nodes = all_nodes()
    q = q.strip()
    if not q:
        return _popular_mix(nodes)[:limit]
    ql = q.lower()
    tiers: list[tuple[int, MemeNode]] = []
    for node in nodes:
        names = [node.name.lower(), *(a.lower() for a in node.aliases)]
        if ql in names:
            tiers.append((0, node))
        elif any(n.startswith(ql) for n in names):
            tiers.append((1, node))
        elif any(ql in n for n in names):
            tiers.append((2, node))
    tiers.sort(key=lambda t: t[0])
    return [node for _, node in tiers[:limit]]


def random_node_id() -> str | None:
    """A random established non-format_class node id, preferring ones with at least one link."""
    row = db.fetch_one(
        """
        SELECT id FROM nodes
        WHERE status = 'established' AND kind <> 'format_class'
          AND EXISTS (SELECT 1 FROM links l WHERE l.child_id = nodes.id)
        ORDER BY random() LIMIT 1
        """
    )
    if row is None:
        row = db.fetch_one(
            """
            SELECT id FROM nodes
            WHERE status = 'established' AND kind <> 'format_class'
            ORDER BY random() LIMIT 1
            """
        )
    return row["id"] if row else None


def name_index() -> list[tuple[str, str]]:
    """(name_or_alias, node_id) for every node name and every alias."""
    rows = db.fetch_all("SELECT id, name, aliases FROM nodes")
    pairs: list[tuple[str, str]] = []
    for row in rows:
        pairs.append((row["name"], row["id"]))
        pairs.extend((alias, row["id"]) for alias in row["aliases"])
    return pairs


def node_kinds() -> dict[str, Kind]:
    """Every node id with its kind; cheaper than `all_nodes`, which joins the sighting counts."""
    rows = db.fetch_all("SELECT id, kind FROM nodes")
    return {row["id"]: row["kind"] for row in rows}


def root_nodes() -> list[MemeNode]:
    """Every established format_class node."""
    return _fetch_nodes("WHERE n.kind = 'format_class' AND n.status = 'established'")


def all_links() -> list[Link]:
    """Every link in the archive."""
    return [_row_to_link(r) for r in db.fetch_all("SELECT * FROM links")]


def get_link(child_id: str, axis: Axis) -> Link | None:
    """The link for child_id on this axis, or None."""
    row = db.fetch_one("SELECT * FROM links WHERE child_id = %s AND axis = %s", (child_id, axis))
    return _row_to_link(row) if row else None


def upsert_node(node: MemeNode) -> None:
    """Insert or update a node's descriptive columns; sightings counters are computed elsewhere."""
    db.execute(
        """
        INSERT INTO nodes (id, name, aliases, kind, latin_name, image_url, image_credit_url,
                            first_seen, date_precision, summary, status)
        VALUES (%(id)s, %(name)s, %(aliases)s, %(kind)s, %(latin_name)s, %(image_url)s,
                %(image_credit_url)s, %(first_seen)s, %(date_precision)s, %(summary)s, %(status)s)
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name, aliases = EXCLUDED.aliases, kind = EXCLUDED.kind,
            latin_name = EXCLUDED.latin_name, image_url = EXCLUDED.image_url,
            image_credit_url = EXCLUDED.image_credit_url, first_seen = EXCLUDED.first_seen,
            date_precision = EXCLUDED.date_precision, summary = EXCLUDED.summary,
            status = EXCLUDED.status
        """,
        {
            "id": node.id,
            "name": node.name,
            "aliases": node.aliases,
            "kind": node.kind,
            "latin_name": node.latin_name,
            "image_url": node.image_url,
            "image_credit_url": node.image_credit_url,
            "first_seen": node.first_seen,
            "date_precision": node.date_precision,
            "summary": node.summary,
            "status": node.status,
        },
    )


def add_alias(node_id: str, alias: str) -> None:
    """Append alias to node_id's aliases, skipping it if it duplicates an alias or the name."""
    row = db.fetch_one("SELECT name, aliases FROM nodes WHERE id = %s", (node_id,))
    if row is None:
        return
    taken = {a.lower() for a in row["aliases"]} | {row["name"].lower()}
    if alias.lower() in taken:
        return
    db.execute(
        "UPDATE nodes SET aliases = array_append(aliases, %s) WHERE id = %s", (alias, node_id)
    )


def set_node_image(node_id: str, image_url: str, credit_url: str) -> None:
    """Set a node's image and credit URL."""
    db.execute(
        "UPDATE nodes SET image_url = %s, image_credit_url = %s WHERE id = %s",
        (image_url, credit_url, node_id),
    )


def set_node_status(node_id: str, status: NodeStatus) -> None:
    """Set a node's status (established or specimen)."""
    db.execute("UPDATE nodes SET status = %s WHERE id = %s", (status, node_id))


def set_node_nsfw(node_id: str, nsfw: bool) -> None:
    """Set a node's nsfw flag (the backfill and the manual override script)."""
    db.execute("UPDATE nodes SET nsfw = %s WHERE id = %s", (nsfw, node_id))


def set_sighting_nsfw(sid: str, nsfw: bool) -> None:
    """Set a sighting's nsfw flag (the backfill and the manual override script)."""
    db.execute("UPDATE sightings SET nsfw = %s WHERE id = %s", (nsfw, sid))


def nodes_needing_nsfw_label(relabel: bool = False) -> list[MemeNode]:
    """Nodes with an image to label: unlabelled only, unless `relabel` asks for every one."""
    where = "WHERE n.image_url IS NOT NULL"
    if not relabel:
        where += " AND n.nsfw IS NULL"
    return _fetch_nodes(where)


def sightings_needing_nsfw_label(relabel: bool = False) -> list[db.Row]:
    """Raw sighting rows to label: unlabelled only, unless `relabel` asks for every one."""
    where = "" if relabel else "WHERE nsfw IS NULL"
    return db.fetch_all(f"SELECT * FROM sightings {where} ORDER BY seen_at")


def upsert_link(link: Link) -> None:
    """Insert a link, replacing the parent and evidence if (child_id, axis) already exists."""
    db.execute(
        """
        INSERT INTO links (child_id, parent_id, axis, status, quote, source_url, source_title)
        VALUES (%(child_id)s, %(parent_id)s, %(axis)s, %(status)s, %(quote)s, %(source_url)s,
                %(source_title)s)
        ON CONFLICT (child_id, axis) DO UPDATE SET
            parent_id = EXCLUDED.parent_id, status = EXCLUDED.status, quote = EXCLUDED.quote,
            source_url = EXCLUDED.source_url, source_title = EXCLUDED.source_title
        """,
        link.model_dump(),
    )


def cite_link(child_id: str, axis: Axis, evidence: Evidence) -> Link | None:
    """Flip an existing link to cited with this evidence; returns the updated link or None."""
    row = db.fetch_one(
        """
        UPDATE links SET status = 'cited', quote = %s, source_url = %s, source_title = %s
        WHERE child_id = %s AND axis = %s
        RETURNING *
        """,
        (evidence.quote, evidence.source_url, evidence.source_title, child_id, axis),
    )
    return _row_to_link(row) if row else None


def sighting_id(post_url: str) -> str:
    """The first 12 hex characters of sha1(post_url)."""
    return hashlib.sha1(post_url.encode(), usedforsecurity=False).hexdigest()[:12]


def sighting_row(sid: str) -> db.Row | None:
    """One raw sightings row (vision included), or None."""
    return db.fetch_one("SELECT * FROM sightings WHERE id = %s", (sid,))


def known_post_urls(urls: Sequence[str]) -> set[str]:
    """Which of these post URLs are already in the archive."""
    rows = db.fetch_all("SELECT post_url FROM sightings WHERE post_url = ANY(%s)", (list(urls),))
    return {r["post_url"] for r in rows}


def insert_sighting(
    post: Post,
    vision: VisionLabel | None,
    node_id: str | None,
    state: SightingState,
    seen_at: datetime | None = None,
    nsfw: bool | None = None,
    *,
    look_error: str | None = None,
    fingerprint: str | None = None,
    duplicate_of: str | None = None,
) -> str | None:
    """Insert a sighting if its post_url is new; returns the id, or None if it already existed.

    `seen_at` defaults to now; a backfill passes the post's own time so old posts
    do not arrive on the wall as if they were new. `nsfw` is used only when `vision`
    is None (e.g. loading mock fixtures that carry a pre-decided label of their own).
    `look_error` says why the image was never read; `duplicate_of` marks a repost of another
    sighting, which then stays off the wall.
    """
    sid = sighting_id(post.post_url)
    row = db.fetch_one(
        """
        INSERT INTO sightings (id, platform, source, post_url, image_url, title, author, posted_at,
                                vision, node_id, state, seen_at, nsfw, look_error, fingerprint,
                                duplicate_of)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, COALESCE(%s, now()), %s, %s, %s, %s)
        ON CONFLICT (post_url) DO NOTHING
        RETURNING id
        """,
        (
            sid,
            post.platform,
            post.source,
            post.post_url,
            post.image_url,
            post.title,
            post.author,
            post.posted_at,
            Json(vision.model_dump(mode="json")) if vision else None,
            node_id,
            state,
            seen_at,
            vision.nsfw if vision else nsfw,
            look_error,
            fingerprint,
            duplicate_of,
        ),
    )
    return row["id"] if row else None


WallCursor = tuple[datetime, str]


def encode_wall_cursor(posted_at: datetime, sighting_id_: str) -> str:
    """Turn a (posted_at, id) keyset position into the opaque `before`/`next_before` string."""
    return f"{posted_at.isoformat()}_{sighting_id_}"


def decode_wall_cursor(cursor: str) -> WallCursor:
    """Parse a `before` cursor; raises ValueError on anything malformed (the route answers 400)."""
    ts, sep, sid = cursor.rpartition("_")
    if not sep or not ts or not sid:
        raise ValueError("Malformed wall cursor.")
    try:
        return datetime.fromisoformat(ts), sid
    except ValueError as exc:
        raise ValueError("Malformed wall cursor.") from exc


def _wall_query(
    since: datetime | None,
    before: WallCursor | None,
    limit: int,
    include_sensitive: bool,
) -> tuple[str, db.Params]:
    """By default only nsfw = false sightings: null (unlabelled) and true are kept off the wall.

    `include_sensitive` drops that filter entirely, for a viewer who asked to see them.
    `since` (ingestion time) picks up live arrivals; `before` is a keyset cursor over the
    sort order itself (posted_at, id both DESC, so ties on posted_at are broken deterministically)
    that picks up older pages. Either, both or neither may be set. A repost of another sighting
    (`duplicate_of` set) is never shown.
    """
    clauses = ["s.duplicate_of IS NULL"]
    if not include_sensitive:
        clauses.append("s.nsfw = false")
    params: list[object] = []
    if since is not None:
        clauses.append("s.seen_at > %s")
        params.append(since)
    if before is not None:
        clauses.append("(s.posted_at, s.id) < (%s, %s)")
        params.extend(before)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return (
        _WALL_SELECT + f"{where} ORDER BY s.posted_at DESC, s.id DESC LIMIT %s",
        tuple(params),
    )


def wall(
    since: datetime | None,
    limit: int,
    include_sensitive: bool = False,
    before: WallCursor | None = None,
) -> list[Sighting]:
    """Sightings for the wall: newest by posted_at (id DESC tiebreak), filtered by since/before."""
    query = _wall_query(since, before, limit, include_sensitive)
    return [_row_to_sighting(r) for r in db.fetch_all(*query)]


def _ceil_ms(moment: datetime) -> datetime:
    extra = moment.microsecond % 1000
    return moment + timedelta(microseconds=1000 - extra) if extra else moment


def wall_page(
    since: datetime | None,
    limit: int,
    include_sensitive: bool = False,
    before: WallCursor | None = None,
) -> tuple[list[Sighting], datetime, str | None]:
    """Wall sightings, the `since` cursor for the next poll, and `before` for the next older page.

    The `since` cursor is the newest ingestion time in the same snapshot as the rows, taken
    from the database clock, so a poll neither misses nor repeats a sighting when the
    API host's clock differs. It is rounded up to a millisecond because browsers
    drop microseconds when they round-trip a timestamp.

    The `before` cursor (`next_before`) is the keyset position of the oldest row returned,
    to pass back as `before` on the next request; it is `None` once the wall is exhausted.
    One extra row is fetched (never returned) just to tell exhaustion apart from a page that
    happens to end exactly on the limit.
    """
    with db.connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        newest = conn.execute(
            "SELECT COALESCE(max(seen_at), now()) AS at FROM sightings"
        ).fetchone()
        rows = conn.execute(*_wall_query(since, before, limit + 1, include_sensitive)).fetchall()
    cursor: datetime = newest["at"] if newest else datetime.now(UTC)
    has_more = len(rows) > limit
    page = rows[:limit]
    next_before = (
        encode_wall_cursor(page[-1]["posted_at"], page[-1]["id"]) if has_more and page else None
    )
    return [_row_to_sighting(r) for r in page], _ceil_ms(cursor), next_before


def counts() -> dict[str, int]:
    """Row counts per table, for health checks and scripts."""
    row = db.fetch_one(
        """
        SELECT (SELECT count(*) FROM nodes) AS nodes, (SELECT count(*) FROM links) AS links,
               (SELECT count(*) FROM sightings) AS sightings,
               (SELECT count(*) FROM history) AS history
        """
    )
    return {key: int(value) for key, value in (row or {}).items()}


def node_sightings(
    node_id: str,
    limit: int = 48,
    include_sensitive: bool = False,
    names: Sequence[str] | None = None,
) -> list[tuple[Sighting, dict[str, Any] | None]]:
    """Sightings of one node with their saved vision labels, newest first; never reposts.

    With `names` (the lower-cased name and aliases of a character), also the resolved sightings
    stamped with another node whose vision subjects name this character: Jensen Huang drawn into
    a Drake template is stamped Drake, but belongs on his page too. By default nsfw (true or
    unlabelled) sightings are excluded; `include_sensitive` keeps them.
    """
    sensitive_filter = "" if include_sensitive else " AND s.nsfw = false"
    also = ""
    params: dict[str, Any] = {"id": node_id, "limit": limit}
    if names:
        also = """
            OR (s.state = 'resolved' AND s.node_id <> %(id)s AND EXISTS (
                SELECT 1
                FROM jsonb_array_elements_text(COALESCE(s.vision->'subjects', '[]'::jsonb)) AS subj
                WHERE lower(subj) = ANY(%(names)s)))"""
        params["names"] = [n.lower() for n in names]
    rows = db.fetch_all(
        _WALL_SELECT
        + f" WHERE s.duplicate_of IS NULL AND (s.node_id = %(id)s{also}){sensitive_filter}"
        + " ORDER BY s.posted_at DESC LIMIT %(limit)s",
        params,
    )
    return [(_row_to_sighting(r), r.get("vision")) for r in rows]


def sightings_for_node(
    node_id: str, limit: int = 48, include_sensitive: bool = False
) -> list[Sighting]:
    """Sightings stamped with one node, newest first (`node_sightings` without the extras)."""
    return [s for s, _ in node_sightings(node_id, limit, include_sensitive)]


def pending_sightings(hours: int = 72) -> list[db.Row]:
    """Raw pending-sighting rows (incl. vision) from the last `hours`, by seen_at."""
    return db.fetch_all(
        """
        SELECT * FROM sightings
        WHERE state = 'pending' AND duplicate_of IS NULL
          AND seen_at > now() - (%s || ' hours')::interval
        ORDER BY seen_at
        """,
        (hours,),
    )


# Unstamps the sightings of nodes about to be deleted: a meme goes back to pending, so it keeps an
# "unidentified" stamp and can be matched again; anything else becomes unclassified.
_DETACH_SQL = """
    UPDATE sightings
    SET node_id = NULL,
        state = CASE WHEN (vision->>'is_meme') = 'true' THEN 'pending' ELSE 'unclassified' END
    WHERE node_id = ANY(%s)
"""


def delete_nodes(ids: Sequence[str]) -> int:
    """Delete these nodes; their links and history go with them.

    Sightings attached to them are kept but lose their stamp, because a resolved sighting may
    not lose its node: a meme goes back to pending (it can be re-matched), anything else becomes
    unclassified. Returns the number of nodes removed.
    """
    if not ids:
        return 0
    with db.connection() as conn:
        conn.execute(
            _DETACH_SQL,
            (list(ids),),
        )
        return conn.execute("DELETE FROM nodes WHERE id = ANY(%s)", (list(ids),)).rowcount


def pending_with_vision(hours: int | None = None) -> list[db.Row]:
    """Pending sightings with a saved vision label (id, title, vision), oldest first.

    Reposts (`duplicate_of` set) are left out: they follow their original's stamp.

    `hours` limits them to those seen that recently; None means every one, however old.
    """
    where = ""
    params: tuple[int, ...] = ()
    if hours is not None:
        where = " AND seen_at > now() - (%s || ' hours')::interval"
        params = (hours,)
    return db.fetch_all(
        "SELECT id, title, vision FROM sightings"
        " WHERE state = 'pending' AND vision IS NOT NULL AND duplicate_of IS NULL"
        f"{where} ORDER BY seen_at",
        params,
    )


def attach_sightings(sighting_ids: Sequence[str], node_id: str) -> int:
    """Attach these sightings to node_id and mark them resolved; returns the number changed.

    Their reposts (`duplicate_of` one of them) get the same stamp, but are not counted.
    """
    ids = list(sighting_ids)
    with db.connection() as conn:
        changed = conn.execute(
            "UPDATE sightings SET node_id = %s, state = 'resolved' WHERE id = ANY(%s)",
            (node_id, ids),
        ).rowcount
        conn.execute(
            "UPDATE sightings SET node_id = %s, state = 'resolved' WHERE duplicate_of = ANY(%s)",
            (node_id, ids),
        )
    return changed


def update_sighting_label(
    sid: str,
    vision: VisionLabel,
    node_id: str | None,
    state: SightingState,
    *,
    image_url: str,
    fingerprint: str | None,
) -> None:
    """Save a fresh look at one sighting: its label, stamp, nsfw flag, image URL and fingerprint.

    Clears `look_error`. The sighting's reposts take the same stamp and nsfw flag.
    """
    with db.connection() as conn:
        conn.execute(
            """
            UPDATE sightings
            SET vision = %s, node_id = %s, state = %s, nsfw = %s, image_url = %s,
                fingerprint = %s, look_error = NULL
            WHERE id = %s
            """,
            (
                Json(vision.model_dump(mode="json")),
                node_id,
                state,
                vision.nsfw,
                image_url,
                fingerprint,
                sid,
            ),
        )
        conn.execute(
            "UPDATE sightings SET node_id = %s, state = %s, nsfw = %s WHERE duplicate_of = %s",
            (node_id, state, vision.nsfw, sid),
        )


def set_sighting_state(sids: Sequence[str], state: SightingState) -> int:
    """Set the state of unstamped sightings (node_id stays as it is); returns how many changed."""
    return db.execute(
        "UPDATE sightings SET state = %s WHERE id = ANY(%s) AND node_id IS NULL",
        (state, list(sids)),
    )


def set_image_check(sid: str, fingerprint: str | None, look_error: str | None) -> None:
    """Record what re-reading one sighting's image found: its fingerprint, or why it failed."""
    db.execute(
        "UPDATE sightings SET fingerprint = %s, look_error = %s WHERE id = %s",
        (fingerprint, look_error, sid),
    )


def mark_duplicates(keeper_id: str, ids: Sequence[str]) -> int:
    """Make `ids` reposts of `keeper_id`, sharing its stamp; returns how many were marked.

    Reposts that pointed at one of `ids` are moved onto the keeper too.
    """
    others = [i for i in ids if i != keeper_id]
    if not others:
        return 0
    with db.connection() as conn:
        conn.execute(
            """
            UPDATE sightings AS s
            SET duplicate_of = k.id, state = k.state, node_id = k.node_id
            FROM sightings AS k
            WHERE k.id = %s AND (s.id = ANY(%s) OR s.duplicate_of = ANY(%s))
            """,
            (keeper_id, others, others),
        )
        return len(others)


def dedupe_candidates(days: int = 7) -> list[db.Row]:
    """Sightings a new post may repeat: not themselves reposts, posted in the last `days`.

    Each row has what `dedupe.Candidate` needs plus the stamp a repost copies
    (`state`, `node_id`, `vision`, `nsfw`).
    """
    return db.fetch_all(
        """
        SELECT id, image_url, fingerprint, author, title, posted_at, state, node_id, vision, nsfw
        FROM sightings
        WHERE duplicate_of IS NULL AND posted_at > now() - make_interval(days => %s)
        ORDER BY posted_at
        """,
        (days,),
    )


def sightings_with_image(image_urls: Sequence[str]) -> list[db.Row]:
    """Non-repost sightings showing exactly one of these image URLs, however old (rule D1)."""
    return db.fetch_all(
        """
        SELECT id, image_url, fingerprint, author, title, posted_at, state, node_id, vision, nsfw
        FROM sightings
        WHERE duplicate_of IS NULL AND image_url = ANY(%s)
        ORDER BY posted_at
        """,
        (list(image_urls),),
    )


def add_history(
    type: HistoryType,
    node_id: str | None,
    message: str,
    source_url: str | None = None,
    pending: bool = False,
    payload: dict[str, Any] | None = None,
) -> str:
    """Record a history row; returns its id."""
    row = db.fetch_one(
        """
        INSERT INTO history (type, node_id, message, source_url, pending, payload)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            type,
            node_id,
            message,
            source_url,
            pending,
            Json(payload) if payload is not None else None,
        ),
    )
    assert row is not None
    return str(row["id"])


def history_for(node_ids: Sequence[str], limit: int = 30) -> list[HistoryItem]:
    """History rows for these nodes, newest first."""
    rows = db.fetch_all(
        "SELECT * FROM history WHERE node_id = ANY(%s) ORDER BY ts DESC LIMIT %s",
        (list(node_ids), limit),
    )
    return [_row_to_history(r) for r in rows]


# A meme counts as rising only on real evidence: enough distinct posts today, well above its usual
# rate, and a baseline the archive actually observed. Two posts against an empty history is noise.
RISING_MIN_POSTS = 3
RISING_MIN_RATIO = 2.0
RISING_MIN_OBSERVED_DAYS = 3.0
_PRIOR_WINDOW_DAYS = 6.0


def spike_baseline(count_24h: int, prior_count: int, observed_days: float) -> float | None:
    """The usual posts per day, if today's count is a real spike over it; otherwise None.

    `observed_days` is how long the archive has been collecting. The usual rate is taken over
    the days of the prior window that were actually observed, never over days with no data, and
    nothing counts as rising until at least RISING_MIN_OBSERVED_DAYS have been observed.
    """
    if observed_days < RISING_MIN_OBSERVED_DAYS or count_24h < RISING_MIN_POSTS:
        return None
    prior_days = min(_PRIOR_WINDOW_DAYS, observed_days - 1.0)
    mean = prior_count / prior_days
    if count_24h < RISING_MIN_RATIO * mean:
        return None
    return round(mean, 1)


def _observed_days() -> float:
    """How many days ago the first sighting was recorded; 0 for an empty archive."""
    row = db.fetch_one(
        "SELECT extract(epoch FROM now() - min(seen_at)) / 86400 AS days FROM sightings"
    )
    return float(row["days"]) if row is not None and row["days"] is not None else 0.0


def _rising_candidates() -> list[tuple[str, int, float]]:
    observed_days = _observed_days()
    if observed_days < RISING_MIN_OBSERVED_DAYS:
        return []
    # Distinct titles, so one post cross-posted to several communities counts once.
    rows = db.fetch_all(
        """
        SELECT node_id,
            count(DISTINCT lower(title))
                FILTER (WHERE posted_at >= now() - interval '24 hours') AS count_24h,
            count(DISTINCT lower(title)) FILTER (
                WHERE posted_at < now() - interval '24 hours'
                  AND posted_at >= now() - interval '7 days'
            ) AS prior_count
        FROM sightings
        WHERE node_id IS NOT NULL AND nsfw = false AND duplicate_of IS NULL
        GROUP BY node_id
        """
    )
    candidates = []
    for row in rows:
        baseline = spike_baseline(row["count_24h"], row["prior_count"], observed_days)
        if baseline is not None:
            candidates.append((row["node_id"], row["count_24h"], baseline))
    candidates.sort(key=lambda c: c[1] - c[2], reverse=True)
    return candidates


def rising(limit: int = 6) -> list[RisingFamily]:
    """Nodes whose sightings spiked in the last 24h against the preceding week's daily average."""
    candidates = _rising_candidates()[:limit]
    nodes = {n.id: n for n in get_nodes([c[0] for c in candidates])}
    return [
        RisingFamily(node=nodes[node_id], count_24h=count_24h, daily_mean_prior=daily_mean_prior)
        for node_id, count_24h, daily_mean_prior in candidates
        if node_id in nodes
    ]


def new_specimens(days: int = 7) -> list[MemeNode]:
    """Specimen nodes created within the last `days`, newest first."""
    return _fetch_nodes(
        "WHERE n.status = 'specimen' AND n.created_at >= now() - (%s || ' days')::interval "
        "ORDER BY n.created_at DESC",
        (days,),
    )


def expire_specimens(days: int = 7) -> list[str]:
    """Delete specimens with no sighting in `days`; their sightings lose the stamp.

    As in `delete_nodes`, a meme goes back to pending and anything else becomes unclassified.
    """
    stale = """
        SELECT n.id FROM nodes n
        WHERE n.status = 'specimen' AND n.created_at < now() - make_interval(days => %(days)s)
          AND NOT EXISTS (
              SELECT 1 FROM sightings s
              WHERE s.node_id = n.id AND s.posted_at > now() - make_interval(days => %(days)s)
          )
    """
    with db.connection() as conn:
        ids = [row["id"] for row in conn.execute(stale, {"days": days}).fetchall()]
        conn.execute(
            _DETACH_SQL,
            (ids,),
        )
        conn.execute("DELETE FROM nodes WHERE id = ANY(%s)", (ids,))
    return ids


# --- cost guards and webhook bookkeeping (the policy is in budget.py and live.py) ---------------


def add_spend(kind: str, amount: float) -> None:
    """Add `amount` units of `kind` to the current hour's row in `spend`."""
    db.execute(
        "INSERT INTO spend (hour, kind, amount) VALUES (date_trunc('hour', now()), %s, %s) "
        "ON CONFLICT (hour, kind) DO UPDATE SET amount = spend.amount + EXCLUDED.amount",
        (kind, amount),
    )


def spend_total(kind: str, hours: int) -> float:
    """Units of `kind` spent in the current hour and the `hours - 1` before it."""
    row = db.fetch_one(
        "SELECT coalesce(sum(amount), 0) AS total FROM spend WHERE kind = %s "
        "AND hour >= date_trunc('hour', now()) - make_interval(hours => %s)",
        (kind, hours - 1),
    )
    return float(row["total"]) if row is not None else 0.0


def get_state(key: str) -> str | None:
    """A value from `app_state`, or None when the key was never set."""
    row = db.fetch_one("SELECT value FROM app_state WHERE key = %s", (key,))
    return str(row["value"]) if row is not None else None


def set_state(key: str, value: str) -> None:
    """Set one `app_state` value, stamping when it changed."""
    db.execute(
        "INSERT INTO app_state (key, value, updated_at) VALUES (%s, %s, now()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
        (key, value),
    )


def clear_state(key: str) -> None:
    """Remove one `app_state` key."""
    db.execute("DELETE FROM app_state WHERE key = %s", (key,))


def state_age(key: str) -> float | None:
    """Seconds since `key` was last set in `app_state`, or None when it never was."""
    row = db.fetch_one(
        "SELECT extract(epoch FROM now() - updated_at) AS age FROM app_state WHERE key = %s",
        (key,),
    )
    return float(row["age"]) if row is not None else None


def claim_turn(key: str, every_s: float) -> bool:
    """Stamp `key` unless it was stamped less than `every_s` ago; True when this call stamped it."""
    claimed = db.execute(
        "INSERT INTO app_state (key, value, updated_at) VALUES (%s, '', now()) "
        "ON CONFLICT (key) DO UPDATE SET updated_at = now() "
        "WHERE app_state.updated_at <= now() - make_interval(secs => %s)",
        (key, every_s),
    )
    return claimed == 1


def save_monitor(monitor_id: str, feed_key: str, secret: str | None) -> None:
    """Remember a monitor this archive created, with its webhook signing secret."""
    db.execute(
        "INSERT INTO webhook_monitors (id, feed_key, secret) VALUES (%s, %s, %s) "
        "ON CONFLICT (id) DO UPDATE SET feed_key = EXCLUDED.feed_key, secret = EXCLUDED.secret",
        (monitor_id, feed_key, secret),
    )


def monitor_row(monitor_id: str) -> tuple[str, str | None] | None:
    """A saved monitor's (feed key, signing secret), or None when it is not one of ours."""
    row = db.fetch_one("SELECT feed_key, secret FROM webhook_monitors WHERE id = %s", (monitor_id,))
    return (str(row["feed_key"]), row["secret"]) if row is not None else None


def monitor_ids() -> list[str]:
    """Every saved monitor id."""
    return [str(r["id"]) for r in db.fetch_all("SELECT id FROM webhook_monitors ORDER BY id")]


def delete_monitor_row(monitor_id: str) -> None:
    """Forget a saved monitor."""
    db.execute("DELETE FROM webhook_monitors WHERE id = %s", (monitor_id,))


def first_delivery(event_id: str) -> bool:
    """Record a webhook event id; True only the first time this id is seen."""
    inserted = db.execute(
        "INSERT INTO webhook_events (id) VALUES (%s) ON CONFLICT (id) DO NOTHING", (event_id,)
    )
    return inserted == 1
