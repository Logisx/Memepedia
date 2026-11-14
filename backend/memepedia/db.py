"""Postgres access: one connection pool, the schema loader and small query helpers.

With DATABASE_URL set the backend talks to that server (Aiven in production). Without it,
a local Postgres from the `pgserver` dev dependency is started under backend/.pgdata and
MEMEPEDIA_DB names the database on it (default "memepedia").
Tests call `configure(local_url("memepedia_test"))` so they can never touch DATABASE_URL.
`reset_schema` refuses to run on anything but the local dev server.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from memepedia.config import PGDATA_DIR, get_settings

Row = dict[str, Any]
Params = Sequence[Any] | dict[str, Any]

_SCHEMA = Path(__file__).with_name("schema.sql")
_state: dict[str, Any] = {"url": None, "pool": None, "server": None}


class NotLocalDatabaseError(RuntimeError):
    """A dev-only action was asked of a database other than the local development server."""


def _local_server_uri() -> str:
    if _state["server"] is None:
        import pgserver

        _state["server"] = pgserver.get_server(PGDATA_DIR, cleanup_mode="stop")
    return str(_state["server"].get_uri())


def local_url(dbname: str = "memepedia") -> str:
    """Connection string for a database on the local dev server, created if missing."""
    admin = _local_server_uri()
    with psycopg.connect(admin, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    return make_conninfo(admin, dbname=dbname)


def is_local_url(url: str) -> bool:
    """True only for a unix-socket connection into the local dev server's backend/.pgdata."""
    try:
        params = conninfo_to_dict(url)
    except psycopg.ProgrammingError:
        return False
    host = params.get("host")
    if "hostaddr" in params or not isinstance(host, str) or not host.startswith("/"):
        return False
    return Path(host).resolve() == PGDATA_DIR.resolve()


def configure(url: str) -> None:
    """Point the pool at an explicit database, closing any pool already open."""
    close()
    _state["url"] = url


def database_url() -> str:
    """The configured URL, else DATABASE_URL, else the local dev database."""
    if _state["url"] is None:
        settings = get_settings()
        _state["url"] = settings.database_url or local_url(settings.local_db_name)
    return str(_state["url"])


def require_local(action: str) -> None:
    """Refuse `action` unless the active database is the local dev server; never connects."""
    if not is_local_url(database_url()):
        raise NotLocalDatabaseError(
            f"{action} refused: the active database is not the local development server "
            "(backend/.pgdata). DATABASE_URL, when set, takes precedence over MEMEPEDIA_DB."
        )


def _configure_connection(conn: psycopg.Connection[DictRow]) -> None:
    conn.execute("SET TIME ZONE 'UTC'")
    conn.commit()


def pool() -> ConnectionPool[psycopg.Connection[DictRow]]:
    """The shared pool, opened on first use."""
    if _state["pool"] is None:
        _state["pool"] = ConnectionPool(
            database_url(),
            min_size=1,
            max_size=8,
            kwargs={"row_factory": dict_row},
            configure=_configure_connection,
            open=True,
        )
    opened: ConnectionPool[psycopg.Connection[DictRow]] = _state["pool"]
    return opened


def close() -> None:
    """Close the pool; the next query opens a new one."""
    if _state["pool"] is not None:
        _state["pool"].close()
        _state["pool"] = None


@contextmanager
def connection() -> Iterator[psycopg.Connection[DictRow]]:
    """A pooled connection; commits on success, rolls back on error."""
    with pool().connection() as conn:
        yield conn


def init_schema() -> None:
    """Create the four tables if they do not exist."""
    with connection() as conn:
        conn.execute(_SCHEMA.read_text())


def reset_schema() -> None:
    """Drop every table and recreate the schema; only ever on the local dev server."""
    require_local("Resetting the schema")
    with connection() as conn:
        conn.execute("DROP TABLE IF EXISTS history, sightings, links, nodes CASCADE")
    init_schema()


def fetch_all(query: str, params: Params = ()) -> list[Row]:
    with connection() as conn:
        return conn.execute(query, params).fetchall()


def fetch_one(query: str, params: Params = ()) -> Row | None:
    with connection() as conn:
        return conn.execute(query, params).fetchone()


def execute(query: str, params: Params = ()) -> int:
    """Run a statement and return the number of affected rows."""
    with connection() as conn:
        return conn.execute(query, params).rowcount
