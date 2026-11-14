"""Copy every Memepedia table from one database to another, ids included.

Usage (from backend/):

    uv run python scripts/clone_db.py --source production --target staging --dry-run
    uv run python scripts/clone_db.py --source production --target staging --create --freeze
    uv run python scripts/clone_db.py --source staging --target production --restore

Databases are named, never typed out: `production` is DATABASE_URL, `staging` is
STAGING_DATABASE_URL or else the `memepedia_staging` database on production's server, `db:NAME`
is database NAME on production's server, and `env:NAME` reads any other variable. Values come
from the shell first, then the repo's `.env`.

The source is read in one read-only snapshot. The target gets the schema, then all four tables
are emptied and refilled in a single transaction, so a failed copy leaves it as it was. It is
refused when source and target are the same database, and when the target looks like
production unless `--restore` is given; a restore also asks for the database name to be typed
and saves a JSON snapshot of production to backend/.data first. `--freeze` makes the target
read-only for every later session (this script overrides that for its own session).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg import IsolationLevel, sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from memepedia import db
from memepedia.config import DATA_DIR, REPO_ROOT
from memepedia.staging import (
    PRODUCTION_DB_NAMES,
    describe,
    identity,
    resolve_staging_url,
    same_database,
    staging_url,
)

TABLES = ("nodes", "links", "sightings", "history")
SCHEMA = Path(db.__file__).with_name("schema.sql")
RESET_HISTORY_ID = (
    "SELECT setval(pg_get_serial_sequence('history', 'id'), COALESCE(MAX(id), 0) + 1, false) "
    "FROM history"
)
Conn = psycopg.Connection[Any]
Columns = dict[str, list[str]]
Counts = dict[str, int]


class CloneRefusedError(RuntimeError):
    """The copy was refused before anything was written."""


@dataclass(frozen=True)
class Plan:
    """Which database is copied where.

    Attributes:
        source: Connection string read from.
        target: Connection string whose four tables are replaced.
        production: The production connection string (DATABASE_URL), if known.
        restore: Whether writing to production was asked for explicitly.
    """

    source: str
    target: str
    production: str | None
    restore: bool = False


@dataclass(frozen=True)
class Options:
    """How the copy runs.

    Attributes:
        create: Create the target database first when it does not exist.
        freeze: Make the target read-only for every later session.
        dry_run: Only print row counts; write nothing.
        maintenance_db: The database to connect to when creating the target.
    """

    create: bool = False
    freeze: bool = False
    dry_run: bool = False
    maintenance_db: str = "defaultdb"


def looks_like_production(url: str, production: str | None) -> bool:
    """Whether a database is production, or is named like Aiven's production database.

    Args:
        url: The connection string to judge.
        production: The production connection string, if known.

    Returns:
        True when it is the same database as `production` or named like `defaultdb`.
    """
    return same_database(url, production) or identity(url)[2] in PRODUCTION_DB_NAMES


def check_plan(plan: Plan, options: Options = Options()) -> None:
    """Refuse a copy that could damage the wrong database; never connects.

    Args:
        plan: The source, the target and what production is.
        options: How the copy will run.

    Raises:
        CloneRefusedError: The plan is unsafe; the message never contains a connection string.
    """
    try:
        _check(plan, options)
    except psycopg.ProgrammingError:
        raise CloneRefusedError("A connection string could not be read.") from None


def _check(plan: Plan, options: Options) -> None:
    if same_database(plan.source, plan.target):
        raise CloneRefusedError("The source and the target are the same database.")
    if plan.restore and not same_database(plan.target, plan.production):
        raise CloneRefusedError("--restore only ever writes to production (DATABASE_URL).")
    if plan.restore and options.freeze:
        raise CloneRefusedError("--freeze is never applied to production.")
    if not plan.restore and looks_like_production(plan.target, plan.production):
        raise CloneRefusedError("The target looks like production; overwriting it needs --restore.")


def open_source(url: str) -> Conn:
    """A read-only connection whose reads all come from one snapshot.

    Args:
        url: The source connection string.

    Returns:
        A connection in repeatable-read, read-only mode.
    """
    conn = psycopg.connect(url)
    conn.isolation_level = IsolationLevel.REPEATABLE_READ
    conn.read_only = True
    return conn


def open_target(url: str) -> Conn:
    """An autocommit connection that may write even to a frozen database.

    Args:
        url: The target connection string.

    Returns:
        A connection with this session's default read-only flag switched off.
    """
    conn = psycopg.connect(url, autocommit=True)
    conn.execute("SET default_transaction_read_only = off")
    return conn


def table_columns(conn: Conn) -> Columns:
    """Column names of every table in the public schema, in their stored order.

    Args:
        conn: Any connection.

    Returns:
        Table name to its column names.
    """
    rows = conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"
    ).fetchall()
    columns: Columns = {}
    for table, column in rows:
        columns.setdefault(str(table), []).append(str(column))
    return columns


def counts(conn: Conn) -> Counts:
    """Row counts of the four tables.

    Args:
        conn: A connection to a database that has them.

    Returns:
        Table name to its number of rows.
    """
    query = sql.SQL("SELECT count(*) FROM {}")
    rows = {t: conn.execute(query.format(sql.Identifier(t))).fetchone() for t in TABLES}
    return {table: int(row[0]) if row else 0 for table, row in rows.items()}


def source_state(conn: Conn) -> tuple[Columns, Counts]:
    """The source's columns and row counts, refusing a source without a usable archive.

    Args:
        conn: The source connection.

    Returns:
        Its columns and row counts.

    Raises:
        CloneRefusedError: A table is missing or there are no nodes.
    """
    columns = table_columns(conn)
    missing = [table for table in TABLES if table not in columns]
    if missing:
        raise CloneRefusedError(f"The source has no {', '.join(missing)} table.")
    found = counts(conn)
    if found["nodes"] == 0:
        raise CloneRefusedError("The source archive is empty; nothing is copied over the target.")
    return columns, found


def check_columns(source: Columns, target: Columns) -> None:
    """Refuse when a source column has nowhere to go in the target, so no data is dropped.

    Args:
        source: The source's columns.
        target: The target's columns after its schema was applied.

    Raises:
        CloneRefusedError: The target lacks a column the source has.
    """
    lacking = {t: [c for c in source[t] if c not in target.get(t, [])] for t in TABLES}
    lacking = {table: cols for table, cols in lacking.items() if cols}
    if lacking:
        raise CloneRefusedError(
            f"The target schema lacks {lacking}; run from a branch whose schema.sql has them."
        )


def copy_table(src: Conn, dst: Conn, table: str, columns: list[str]) -> None:
    """Stream one table from source to target with COPY, ids and all.

    Args:
        src: The source connection.
        dst: The target connection, inside the copy's transaction.
        table: The table name.
        columns: The columns to copy.
    """
    names = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
    out_query = sql.SQL("COPY {} ({}) TO STDOUT").format(sql.Identifier(table), names)
    in_query = sql.SQL("COPY {} ({}) FROM STDIN").format(sql.Identifier(table), names)
    with src.cursor().copy(out_query) as out, dst.cursor().copy(in_query) as into:
        for block in out:
            into.write(block)


def transfer(src: Conn, dst: Conn, columns: Columns) -> None:
    """Empty the target's four tables and refill them from the source, all in one transaction.

    Args:
        src: The source connection.
        dst: The target connection.
        columns: The source's columns per table.
    """
    with dst.transaction():
        dst.execute("TRUNCATE history, sightings, links, nodes")
        for table in TABLES:
            copy_table(src, dst, table, columns[table])
        dst.execute(RESET_HISTORY_ID)


def create_database(target: str, maintenance_db: str) -> bool:
    """Create the target database when it does not exist yet.

    Args:
        target: The target connection string.
        maintenance_db: An existing database on the same server to connect to.

    Returns:
        True when it was created, False when it already existed.
    """
    dbname = identity(target)[2]
    with psycopg.connect(make_conninfo(target, dbname=maintenance_db), autocommit=True) as conn:
        if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone():
            return False
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    return True


def freeze_database(conn: Conn) -> None:
    """Make every later session on this database read-only by default.

    Args:
        conn: A connection to the database to freeze.
    """
    name = sql.Identifier(conn.info.dbname)
    conn.execute(sql.SQL("ALTER DATABASE {} SET default_transaction_read_only = on").format(name))


def save_snapshot(conn: Conn, path: Path) -> None:
    """Write every row of the four tables to a JSON file.

    Args:
        conn: The database to snapshot.
        path: Where to write it.
    """
    cursor = conn.cursor(row_factory=dict_row)
    query = sql.SQL("SELECT * FROM {}")
    tables = {t: cursor.execute(query.format(sql.Identifier(t))).fetchall() for t in TABLES}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tables, default=str, indent=1))


def confirm_restore(target: str, confirm: Callable[[str], str]) -> None:
    """Ask for production's database name to be typed before it is overwritten.

    Args:
        target: The production connection string.
        confirm: Asks a question and returns the answer (`input` on the command line).

    Raises:
        CloneRefusedError: The answer was not the database name.
    """
    dbname = identity(target)[2]
    prompt = f"This REPLACES every row of production, {describe(target)}. Type {dbname!r}: "
    if confirm(prompt).strip() != dbname:
        raise CloneRefusedError("Restore cancelled: the database name was not typed.")


def report(label: str, url: str, found: Counts | None) -> None:
    """Print one side's row counts.

    Args:
        label: "source" or "target".
        url: Its connection string (only a masked description is printed).
        found: Its row counts, or None when it has no tables yet.
    """
    shown = ", ".join(f"{t} {n}" for t, n in found.items()) if found else "no tables yet"
    print(f"{label}: {describe(url)}: {shown}")


def target_counts(conn: Conn) -> Counts | None:
    """The target's row counts, or None when it does not have all four tables yet.

    Args:
        conn: The target connection.

    Returns:
        Its row counts, or None.
    """
    columns = table_columns(conn)
    return counts(conn) if all(table in columns for table in TABLES) else None


def prepare_target(plan: Plan, dst: Conn, confirm: Callable[[str], str]) -> None:
    """Confirm a restore, bring the target's schema up to date, then snapshot a restore's rows.

    Args:
        plan: The copy plan.
        dst: The target connection.
        confirm: Asks for the restore confirmation.
    """
    if plan.restore:
        confirm_restore(plan.target, confirm)
    dst.execute(SCHEMA.read_text())
    if plan.restore:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = DATA_DIR / f"before_restore_{stamp}.json"
        save_snapshot(dst, path)
        print(f"Saved production's rows to {path}")


def run_copy(
    plan: Plan, options: Options, src: Conn, dst: Conn, confirm: Callable[[str], str]
) -> Counts:
    """Copy over open connections, then check that both sides hold the same number of rows.

    Args:
        plan: The copy plan.
        options: How the copy runs.
        src: The source connection.
        dst: The target connection.
        confirm: Asks for the restore confirmation.

    Returns:
        The target's row counts afterwards (before them, on a dry run).

    Raises:
        CloneRefusedError: The source is unusable, columns would be lost, or counts differ.
    """
    columns, expected = source_state(src)
    report("source", plan.source, expected)
    report("target before", plan.target, before := target_counts(dst))
    if options.dry_run:
        return before or {}
    prepare_target(plan, dst, confirm)
    check_columns(columns, table_columns(dst))
    transfer(src, dst, columns)
    if options.freeze:
        freeze_database(dst)
    report("target after", plan.target, after := counts(dst))
    if after != expected:
        raise CloneRefusedError("Row counts differ after the copy; check the target by hand.")
    return after


def clone(
    plan: Plan, options: Options = Options(), confirm: Callable[[str], str] = input
) -> Counts:
    """Check the plan, create the target if asked, and copy every table.

    Args:
        plan: Which database is copied where.
        options: How the copy runs.
        confirm: Asks for the restore confirmation.

    Returns:
        The target's row counts afterwards.

    Raises:
        CloneRefusedError: The copy was refused; the target is unchanged.
    """
    check_plan(plan, options)
    creating = options.create and not options.dry_run
    if creating and create_database(plan.target, options.maintenance_db):
        print(f"Created {describe(plan.target)}")
    with open_source(plan.source) as src, open_target(plan.target) as dst:
        return run_copy(plan, options, src, dst, confirm)


def resolve(name: str, env: dict[str, str]) -> str:
    """The connection string behind `production`, `staging`, `db:NAME` or `env:NAME`.

    Args:
        name: The database's name on the command line.
        env: The environment, with `.env` already merged in.

    Returns:
        The connection string.

    Raises:
        CloneRefusedError: The name is unknown or its variable is not set.
    """
    production = env.get("DATABASE_URL")
    if name == "production":
        url = production
    elif name == "staging":
        url = resolve_staging_url(env)
    elif name.startswith("db:"):
        url = staging_url(production, name.removeprefix("db:")) if production else None
    elif name.startswith("env:"):
        url = env.get(name.removeprefix("env:"))
    else:
        raise CloneRefusedError(f"Unknown database {name!r}: use production, staging, db: or env:.")
    if not url:
        raise CloneRefusedError(f"No connection string is set for {name!r}.")
    return url


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Read the command line.

    Args:
        argv: Arguments without the program name, or None for sys.argv.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(description="Copy every Memepedia table to another database.")
    parser.add_argument("--source", required=True, help="production, staging, db:NAME, env:NAME")
    parser.add_argument("--target", required=True, help="production, staging, db:NAME, env:NAME")
    parser.add_argument("--restore", action="store_true", help="allow production as the target")
    parser.add_argument("--create", action="store_true", help="create the target database")
    parser.add_argument("--freeze", action="store_true", help="make the target read-only")
    parser.add_argument("--dry-run", action="store_true", help="only print row counts")
    parser.add_argument("--maintenance-db", default="defaultdb", help="used by --create")
    return parser.parse_args(argv)


def redact(text: str, urls: Sequence[str]) -> str:
    """Replace every host named by the given connection strings with its masked form.

    Args:
        text: A message that may contain host names.
        urls: The connection strings in play.

    Returns:
        The message with each full host name shortened to its last two labels.
    """
    for url in urls:
        try:
            host = identity(url)[0]
        except psycopg.ProgrammingError:
            continue
        text = text.replace(host, "*." + ".".join(host.split(".")[-2:]))
    return text


def main(argv: Sequence[str] | None = None) -> int:
    """Run the copy from the command line.

    Args:
        argv: Arguments without the program name, or None for sys.argv.

    Returns:
        0 on success, 2 when refused, 1 on a database error.
    """
    args = parse_args(argv)
    load_dotenv(REPO_ROOT / ".env")
    env = dict(os.environ)
    urls: list[str] = []
    try:
        urls = [resolve(args.source, env), resolve(args.target, env)]
        plan = Plan(urls[0], urls[1], env.get("DATABASE_URL"), args.restore)
        options = Options(args.create, args.freeze, args.dry_run, args.maintenance_db)
        clone(plan, options)
    except CloneRefusedError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    except psycopg.Error as exc:
        print(f"Database error: {redact(str(exc), urls)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
