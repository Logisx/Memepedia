"""Schema resets and mock fixture loads are refused unless the database is the local dev server."""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest

from memepedia import db
from memepedia.config import PGDATA_DIR
from scripts.load_fixtures import load

FAKE_SECRET = "s3cr3t-password"
FAKE_HOST = "pg-prod.example.com"
NOT_LOCAL_URLS = [
    f"postgresql://admin:{FAKE_SECRET}@{FAKE_HOST}:12345/defaultdb?sslmode=require",
    f"postgresql://admin:{FAKE_SECRET}@localhost:5432/memepedia",
    f"postgresql://admin:{FAKE_SECRET}@localhost.{FAKE_HOST}/memepedia",
    f"postgresql://admin:{FAKE_SECRET}@{FAKE_HOST}/localhost?application_name=localhost",
    f"host=/tmp/.pgdata dbname=memepedia password={FAKE_SECRET}",
    f"host={PGDATA_DIR} hostaddr=203.0.113.7 dbname=memepedia password={FAKE_SECRET}",
    f"host={PGDATA_DIR},{FAKE_HOST} dbname=memepedia password={FAKE_SECRET}",
    f"not a connection string {FAKE_SECRET}",
]


def _no_connection(*args: object, **kwargs: object) -> None:
    raise AssertionError("a database connection was attempted")


@pytest.fixture
def unconnectable(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Any attempt to connect fails the test; the test database is configured again afterwards."""
    test_url = db.database_url()
    monkeypatch.setattr(db, "pool", _no_connection)
    monkeypatch.setattr(psycopg, "connect", _no_connection)
    yield
    db.configure(test_url)


def _assert_refused_quietly(error: pytest.ExceptionInfo[db.NotLocalDatabaseError]) -> None:
    message = str(error.value)
    assert "local development server" in message
    assert FAKE_SECRET not in message
    assert FAKE_HOST not in message


NOT_LOCAL_IDS = [
    "hosted",
    "tcp-localhost",
    "localhost-subdomain",
    "localhost-in-params",
    "other-pgdata-dir",
    "pgdata-with-hostaddr",
    "multi-host",
    "unparseable",
]


@pytest.mark.parametrize("url", NOT_LOCAL_URLS, ids=NOT_LOCAL_IDS)
def test_reset_schema_refused_on_non_local_url(url: str, unconnectable: None) -> None:
    db.configure(url)
    with pytest.raises(db.NotLocalDatabaseError) as error:
        db.reset_schema()
    _assert_refused_quietly(error)


@pytest.mark.parametrize("reset", [False, True])
def test_fixture_load_refused_on_non_local_url(reset: bool, unconnectable: None) -> None:
    db.configure(NOT_LOCAL_URLS[0])
    with pytest.raises(db.NotLocalDatabaseError) as error:
        load(reset=reset)
    _assert_refused_quietly(error)


def test_local_test_database_counts_as_local() -> None:
    assert db.is_local_url(db.local_url("memepedia_test"))


def test_reset_schema_allowed_on_local_database() -> None:
    test_url = db.database_url()
    db.configure(db.local_url("memepedia_guard_test"))
    try:
        db.reset_schema()
        row = db.fetch_one("SELECT count(*) AS n FROM nodes")
        assert row is not None and row["n"] == 0
    finally:
        db.configure(test_url)
