"""The database copy refuses unsafe plans, copies faithfully, and the staging copy stays frozen."""

from __future__ import annotations

import dataclasses
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memepedia import api, db, store  # noqa: E402
from memepedia.config import get_settings  # noqa: E402
from memepedia.staging import STAGING_DB, describe, identity, resolve_staging_url  # noqa: E402
from scripts import clone_db  # noqa: E402
from scripts.clone_db import CloneRefusedError, Options, Plan, check_plan, clone  # noqa: E402
from scripts.load_fixtures import load  # noqa: E402

FAKE_SECRET = "s3cr3t-password"
FAKE_HOST = "pg-prod-1234.example.com"
PROD = f"postgresql://admin:{FAKE_SECRET}@{FAKE_HOST}:12345/defaultdb?sslmode=require"
PROD_OTHER_USER = f"postgresql://reader:other@{FAKE_HOST.upper()}:12345/defaultdb"
STAGING = f"postgresql://admin:{FAKE_SECRET}@{FAKE_HOST}:12345/{STAGING_DB}?sslmode=require"
ELSEWHERE = f"postgresql://admin:{FAKE_SECRET}@db.other.example.org:5432/memepedia"


def _refusal(plan: Plan, options: Options | None = None) -> str:
    with pytest.raises(CloneRefusedError) as error:
        check_plan(plan, options or Options())
    message = str(error.value)
    assert FAKE_SECRET not in message and FAKE_HOST not in message
    return message


def test_same_database_refused_even_with_other_credentials() -> None:
    assert "same database" in _refusal(Plan(PROD, PROD_OTHER_USER, None))


def test_production_target_refused_without_restore() -> None:
    assert "--restore" in _refusal(Plan(STAGING, PROD, PROD))


def test_defaultdb_target_refused_even_when_production_is_unknown() -> None:
    assert "--restore" in _refusal(Plan(ELSEWHERE, PROD, None))


def test_restore_refused_unless_the_target_is_production() -> None:
    assert "only ever writes to production" in _refusal(Plan(PROD, STAGING, PROD, restore=True))


def test_freeze_never_applied_to_production() -> None:
    message = _refusal(Plan(STAGING, PROD, PROD, restore=True), Options(freeze=True))
    assert "never applied to production" in message


def test_unreadable_connection_string_refused_quietly() -> None:
    assert "could not be read" in _refusal(Plan(f"not a url {FAKE_SECRET}", STAGING, PROD))


def test_production_to_staging_allowed() -> None:
    check_plan(Plan(PROD, STAGING, PROD), Options(create=True, freeze=True))


def test_restore_to_production_allowed() -> None:
    check_plan(Plan(STAGING, PROD, PROD, restore=True))


def test_staging_url_sits_next_to_production() -> None:
    staging = resolve_staging_url({"DATABASE_URL": PROD})
    assert staging is not None
    assert identity(staging) == (FAKE_HOST, "12345", STAGING_DB)


def test_explicit_staging_url_wins() -> None:
    values = {"DATABASE_URL": PROD, "STAGING_DATABASE_URL": ELSEWHERE}
    assert resolve_staging_url(values) == ELSEWHERE


def test_resolve_names() -> None:
    env = {"DATABASE_URL": PROD, "OTHER": ELSEWHERE}
    assert clone_db.resolve("production", env) == PROD
    assert clone_db.resolve("env:OTHER", env) == ELSEWHERE
    assert identity(clone_db.resolve("db:memepedia_night", env)) == (
        FAKE_HOST,
        "12345",
        "memepedia_night",
    )
    assert identity(clone_db.resolve("staging", env))[2] == STAGING_DB
    with pytest.raises(CloneRefusedError):
        clone_db.resolve("db:anything", {})
    with pytest.raises(CloneRefusedError):
        clone_db.resolve("env:MISSING", env)
    with pytest.raises(CloneRefusedError):
        clone_db.resolve(PROD, env)


def test_describe_and_redact_hide_secrets() -> None:
    shown = describe(PROD) + clone_db.redact(f"could not reach {FAKE_HOST}", [PROD])
    assert FAKE_SECRET not in shown and FAKE_HOST not in shown and "example.com" in shown


def test_restore_needs_the_database_name_typed() -> None:
    with pytest.raises(CloneRefusedError):
        clone_db.confirm_restore(PROD, lambda prompt: "yes")
    clone_db.confirm_restore(PROD, lambda prompt: "defaultdb\n")


@pytest.fixture(scope="module")
def source_url() -> Iterator[str]:
    """A local database filled with the mock archive, the test database restored afterwards."""
    test_url = db.database_url()
    url = db.local_url("memepedia_clone_src")
    db.configure(url)
    load(reset=True)
    db.configure(test_url)
    yield url


def _rows(url: str, query: str) -> list[tuple[object, ...]]:
    with psycopg.connect(url) as conn:
        return conn.execute(query).fetchall()


def _ids(url: str) -> list[list[tuple[object, ...]]]:
    queries = ["SELECT id FROM nodes", "SELECT child_id, axis FROM links", "SELECT id FROM history"]
    return [sorted(_rows(url, query)) for query in queries]


def test_clone_copies_every_row_with_ids_and_freezes(source_url: str) -> None:
    target = db.local_url("memepedia_clone_dst")
    copied = clone(Plan(source_url, target, None), Options(freeze=True))
    copied_again = clone(Plan(source_url, target, None), Options(freeze=True))
    assert copied == copied_again and copied["nodes"] > 0
    assert _ids(target) == _ids(source_url)
    with psycopg.connect(target) as conn, pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        conn.execute("DELETE FROM history")


def test_history_ids_continue_after_the_copy(source_url: str) -> None:
    target = db.local_url("memepedia_clone_ids")
    clone(Plan(source_url, target, None))
    highest = _rows(target, "SELECT max(id) FROM history")[0][0]
    inserted = _rows(
        target, "INSERT INTO history (type, message) VALUES ('traced', 'x') RETURNING id"
    )
    assert inserted[0][0] == highest + 1  # type: ignore[operator]


def test_empty_source_refused_and_target_untouched(source_url: str) -> None:
    empty = db.local_url("memepedia_clone_empty")
    with psycopg.connect(empty, autocommit=True) as conn:
        conn.execute(clone_db.SCHEMA.read_text())
        conn.execute("TRUNCATE history, sightings, links, nodes")
    target = db.local_url("memepedia_clone_kept")
    before = clone(Plan(source_url, target, None))
    with pytest.raises(CloneRefusedError, match="empty"):
        clone(Plan(empty, target, None))
    assert clone(Plan(target, empty, None)) == before


def test_restore_snapshots_production_first(
    source_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    production = db.local_url("memepedia_clone_prod")
    monkeypatch.setattr(clone_db, "DATA_DIR", tmp_path)
    plan = Plan(source_url, production, production, restore=True)
    with pytest.raises(CloneRefusedError, match="cancelled"):
        clone(plan, confirm=lambda prompt: "no")
    assert not list(tmp_path.iterdir())
    clone(plan, confirm=lambda prompt: "memepedia_clone_prod")
    assert len(list(tmp_path.glob("before_restore_*.json"))) == 1


def test_the_app_reads_a_frozen_database(source_url: str) -> None:
    target = db.local_url("memepedia_clone_dst")
    clone(Plan(source_url, target, None), Options(freeze=True))
    test_url = db.database_url()
    db.configure(target)
    try:
        assert store.counts()["nodes"] > 0
    finally:
        db.configure(test_url)


@pytest.fixture
def read_only_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """The API sees MEMEPEDIA_READ_ONLY switched on."""
    frozen = dataclasses.replace(get_settings(), read_only=True)
    monkeypatch.setattr(api, "get_settings", lambda: frozen)


@pytest.mark.parametrize("path", ["/api/trace", "/api/proposals", "/api/webhooks/context"])
def test_read_only_app_refuses_every_write(
    client: TestClient, read_only_app: None, path: str
) -> None:
    response = client.post(path, json={"query": "Doge"})
    assert response.status_code == 503
    assert response.json()["error"] == api.READ_ONLY_MESSAGE


def test_read_only_app_still_reads(client: TestClient, read_only_app: None) -> None:
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/wall").status_code == 200
