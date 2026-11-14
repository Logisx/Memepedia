"""The frozen staging copy: where its database lives and how to tell two databases apart.

Shared by `deploy.py` (the staging app's secret) and `scripts/clone_db.py` (the copy). The staging
database sits on the same server as production under its own name, so its URL is production's
with the database name swapped, unless STAGING_DATABASE_URL names one explicitly. Nothing here
connects to a database or returns a password.
"""

from __future__ import annotations

from collections.abc import Mapping

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

STAGING_DB = "memepedia_staging"
PRODUCTION_DB_NAMES = frozenset({"defaultdb"})


def identity(url: str) -> tuple[str, str, str]:
    """The (host, port, database name) a connection string points at, defaults filled in.

    Args:
        url: A libpq connection string, URI or keyword/value form.

    Returns:
        The lower-cased host (or socket directory), the port and the database name.

    Raises:
        psycopg.ProgrammingError: The string cannot be parsed.
    """
    params = conninfo_to_dict(url)
    host = str(params.get("host") or params.get("hostaddr") or "localhost").lower()
    port = str(params.get("port") or "5432")
    dbname = str(params.get("dbname") or params.get("user") or "")
    return host, port, dbname


def same_database(first: str | None, second: str | None) -> bool:
    """Whether two connection strings reach the same database; credentials are ignored.

    Args:
        first: A connection string, or None.
        second: Another connection string, or None.

    Returns:
        True when both are set and name the same host, port and database.
    """
    if not first or not second:
        return False
    return identity(first) == identity(second)


def staging_url(production_url: str, dbname: str = STAGING_DB) -> str:
    """Production's connection string pointed at the staging database on the same server.

    Args:
        production_url: The production connection string.
        dbname: The staging database name.

    Returns:
        A keyword/value connection string with the same credentials and the other database.
    """
    return make_conninfo(production_url, dbname=dbname)


def resolve_staging_url(values: Mapping[str, str]) -> str | None:
    """STAGING_DATABASE_URL when set, else the staging database next to DATABASE_URL.

    Args:
        values: Environment-like names to values (the shell environment, `.env`, or both).

    Returns:
        The staging connection string, or None when neither name is set.
    """
    if explicit := values.get("STAGING_DATABASE_URL"):
        return explicit
    production = values.get("DATABASE_URL")
    return staging_url(production) if production else None


def describe(url: str) -> str:
    """A printable name for a database that leaves out user, password and most of the host.

    Args:
        url: A connection string.

    Returns:
        For example "database 'memepedia_staging' on *.aivencloud.com:12345".
    """
    try:
        host, port, dbname = identity(url)
    except psycopg.ProgrammingError:
        return "an unreadable connection string"
    where = "a local socket" if host.startswith("/") else f"*.{_domain(host)}:{port}"
    return f"database '{dbname}' on {where}"


def _domain(host: str) -> str:
    return ".".join(host.split(".")[-2:])
