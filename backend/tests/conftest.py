"""Shared fixtures: a schema-reset test database loaded from the mock fixtures."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memepedia import db  # noqa: E402
from memepedia.api import app  # noqa: E402
from scripts.load_fixtures import load  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def local_test_database() -> None:
    """Every test talks to the local test database, never to the one in DATABASE_URL."""
    db.configure(db.local_url("memepedia_test"))


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    """A TestClient against a freshly loaded test database, for the whole test session."""
    db.configure(db.local_url("memepedia_test"))
    load(reset=True)
    with TestClient(app) as test_client:
        yield test_client
