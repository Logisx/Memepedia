"""Every SQL query in the backend lives here; callers get back contract models."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from psycopg.types.json import Json

from memepedia import db
from memepedia.models import (
    Axis,
    Evidence,
    HistoryItem,
    HistoryType,
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
    WHERE posted_at >= now() - interval '24 hours'
    GROUP BY node_id
) c24 ON c24.node_id = n.id
LEFT JOIN (
    SELECT node_id, count(*) AS c FROM sightings
    WHERE posted_at >= now() - interval '7 days'
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


def known_post_urls(urls: Sequence[str]) -> set[str]:
    """Which of these post URLs are already in the archive."""
    rows = db.fetch_all("SELECT post_url FROM sightings WHERE post_url = ANY(%s)", (list(urls),))
    return {r["post_url"] for r in rows}


def insert_sighting(
    post: Post, vision: VisionLabel | None, node_id: str | None, state: SightingState
) -> str | None:
    """Insert a sighting if its post_url is new; returns the id, or None if it already existed."""
    sid = sighting_id(post.post_url)
    row = db.fetch_one(
        """
        INSERT INTO sightings (id, platform, source, post_url, image_url, title, author, posted_at,
                                vision, node_id, state)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        ),
    )
    return row["id"] if row else None


def wall(since: datetime | None, limit: int) -> list[Sighting]:
    """Sightings for the wall: newest by posted_at, or only those ingested after `since`."""
    if since is None:
        rows = db.fetch_all(_WALL_SELECT + " ORDER BY s.posted_at DESC LIMIT %s", (limit,))
    else:
        rows = db.fetch_all(
            _WALL_SELECT + " WHERE s.seen_at > %s ORDER BY s.posted_at DESC LIMIT %s",
            (since, limit),
        )
    return [_row_to_sighting(r) for r in rows]


def sightings_for_node(node_id: str, limit: int = 12) -> list[Sighting]:
    """Sightings of one node, newest first."""
    rows = db.fetch_all(
        _WALL_SELECT + " WHERE s.node_id = %s ORDER BY s.posted_at DESC LIMIT %s",
        (node_id, limit),
    )
    return [_row_to_sighting(r) for r in rows]


def pending_sightings(hours: int = 72) -> list[db.Row]:
    """Raw pending-sighting rows (incl. vision) from the last `hours`, by seen_at."""
    return db.fetch_all(
        """
        SELECT * FROM sightings
        WHERE state = 'pending' AND seen_at > now() - (%s || ' hours')::interval
        ORDER BY seen_at
        """,
        (hours,),
    )


def attach_sightings(sighting_ids: Sequence[str], node_id: str) -> int:
    """Attach these sightings to node_id and mark them resolved; returns the number changed."""
    return db.execute(
        "UPDATE sightings SET node_id = %s, state = 'resolved' WHERE id = ANY(%s)",
        (node_id, list(sighting_ids)),
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


def _rising_candidates() -> list[tuple[str, int, float]]:
    rows = db.fetch_all(
        """
        SELECT node_id,
            count(*) FILTER (WHERE posted_at >= now() - interval '24 hours') AS count_24h,
            count(*) FILTER (
                WHERE posted_at < now() - interval '24 hours'
                  AND posted_at >= now() - interval '7 days'
            ) AS prior_count
        FROM sightings
        WHERE node_id IS NOT NULL
        GROUP BY node_id
        """
    )
    candidates = []
    for row in rows:
        count_24h, daily_mean_prior = row["count_24h"], round(row["prior_count"] / 6, 1)
        if count_24h >= 2 and count_24h > daily_mean_prior:
            candidates.append((row["node_id"], count_24h, daily_mean_prior))
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
