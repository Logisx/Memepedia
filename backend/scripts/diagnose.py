"""A read-only snapshot of how the archive's sightings are stamped, for the owner to read.

Prints, after the database target:
1. sightings by state, whether the image was read, nsfw, and whether it is a repost;
2. why unread images were not read (`look_error`);
3. orphans: unstamped "unclassified" sightings the vision model did call a meme;
4. groups of sightings sharing one exact image URL (reposts not yet marked);
5. with `--name`, every sighting not stamped with that meme whose title, template guess or
   depicted subjects mention its name or an alias, with what the vision model said.

It never writes (it does not even run the schema migration, so it works before a deploy adds the
new columns: a missing column is reported and skipped) and never calls Gemini or Context.dev.

Usage: uv run python scripts/diagnose.py [--name "Jensen Huang"]

With a repo-root `.env` holding DATABASE_URL this reads the hosted (production) database.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

from memepedia import db, resolver, store

_NEW_COLUMNS = ("look_error", "duplicate_of", "fingerprint")


def sightings_columns() -> set[str]:
    """The columns the sightings table has right now."""
    rows = db.fetch_all(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'sightings'"
    )
    return {r["column_name"] for r in rows}


def state_counts(columns: set[str]) -> list[db.Row]:
    """Sightings by state x read x nsfw (x repost, once that column exists)."""
    repost = "(duplicate_of IS NOT NULL)" if "duplicate_of" in columns else "NULL::boolean"
    return db.fetch_all(
        f"""
        SELECT state, (vision IS NOT NULL) AS read, nsfw, {repost} AS repost, count(*) AS n
        FROM sightings
        GROUP BY 1, 2, 3, 4
        ORDER BY 1, 2, 3, 4
        """
    )


def look_errors() -> list[db.Row]:
    return db.fetch_all(
        "SELECT look_error, count(*) AS n FROM sightings WHERE look_error IS NOT NULL"
        " GROUP BY 1 ORDER BY 2 DESC"
    )


def orphan_count() -> int:
    row = db.fetch_one(
        "SELECT count(*) AS n FROM sightings"
        " WHERE state = 'unclassified' AND node_id IS NULL AND (vision->>'is_meme') = 'true'"
    )
    return int(row["n"]) if row else 0


def same_image_groups(columns: set[str]) -> list[db.Row]:
    """Image URLs shared by more than one sighting that is not already a marked repost."""
    not_repost = "WHERE duplicate_of IS NULL" if "duplicate_of" in columns else ""
    return db.fetch_all(
        f"""
        SELECT image_url, count(*) AS n, array_agg(post_url ORDER BY posted_at) AS posts
        FROM sightings {not_repost}
        GROUP BY image_url HAVING count(*) > 1
        ORDER BY count(*) DESC, min(posted_at)
        """
    )


def mentions(name: str) -> tuple[str | None, list[db.Row]]:
    """The node `name` resolves to, and the sightings not stamped with it that mention it."""
    node_id = resolver.Matcher.from_store(allow_llm=False).exact(name)
    node = store.get_node(node_id) if node_id else None
    names = [name] if node is None else [node.name, *node.aliases]
    patterns = [f"%{n}%" for n in names]
    rows = db.fetch_all(
        """
        SELECT id, state, node_id, title, post_url,
               vision->>'template_guess' AS guess, vision->>'confidence' AS confidence,
               vision->'subjects' AS subjects, vision->>'is_meme' AS is_meme
        FROM sightings
        WHERE node_id IS DISTINCT FROM %(node)s
          AND (title ILIKE ANY(%(p)s) OR vision->>'template_guess' ILIKE ANY(%(p)s)
               OR (vision->'subjects')::text ILIKE ANY(%(p)s))
        ORDER BY posted_at DESC
        """,
        {"node": node_id, "p": patterns},
    )
    return node_id, rows


def _section(out: Callable[[str], None], title: str) -> None:
    out(f"\n== {title} ==")


def report(name: str | None, out: Callable[[str], None] = print) -> None:
    """Prints the whole snapshot through `out`."""
    columns = sightings_columns()
    missing = [c for c in _NEW_COLUMNS if c not in columns]
    if missing:
        out(f"(not deployed yet: no {', '.join(missing)} column; those parts are skipped)")

    _section(out, "sightings by state / read / nsfw / repost")
    for r in state_counts(columns):
        out(
            f"  {r['n']:5d}  {r['state']:12s} read={r['read']!s:5s} nsfw={r['nsfw']!s:5s} "
            f"repost={r['repost']}"
        )

    _section(out, "why images were not read")
    if "look_error" in columns:
        rows = look_errors()
        for r in rows:
            out(f"  {r['n']:5d}  {r['look_error']}")
        if not rows:
            out("  (none recorded)")
    else:
        out("  (look_error column missing)")

    _section(out, "orphans: unclassified memes with no stamp")
    out(f"  {orphan_count()}")

    _section(out, "sightings sharing one exact image URL")
    groups = same_image_groups(columns)
    out(f"  {len(groups)} groups, {sum(g['n'] for g in groups)} sightings")
    for g in groups[:10]:
        out(f"  x{g['n']}  {g['image_url']}")
        for post in g["posts"]:
            out(f"        {post}")

    if name:
        node_id, rows = mentions(name)
        _section(out, f"not stamped {node_id or name!r} but mentioning it")
        if node_id is None:
            out(f"  (no meme named {name!r} in the archive; matching the text only)")
        for r in rows:
            out(f"  {r['id']}  {r['state']:12s} node={r['node_id'] or '-'}  {r['title'][:60]}")
            out(
                f"        guess={r['guess']!r} confidence={r['confidence']} "
                f"is_meme={r['is_meme']} subjects={r['subjects']}"
            )
            out(f"        {r['post_url']}")
        out(f"  {len(rows)} sightings")


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only snapshot of the archive's stamping.")
    parser.add_argument("--name", help="also list posts mentioning this meme but not stamped it")
    args = parser.parse_args()
    print(f"database: {db.describe_target()}")
    report(args.name)


if __name__ == "__main__":
    main()
