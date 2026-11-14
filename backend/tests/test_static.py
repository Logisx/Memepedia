"""The built web app is served from the API's origin, with client-side routes falling back to it."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from memepedia import static
from memepedia.api import app as real_app

INDEX = "<!doctype html><title>Memepedia</title>"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX)
    (root / "favicon.svg").write_text("<svg/>")
    (root / "assets" / "index-abc123.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("outside the build")
    return root


@pytest.fixture
def site(dist: Path) -> TestClient:
    app = FastAPI()

    @app.get("/api/ping")
    def ping() -> dict[str, bool]:
        return {"ok": True}

    assert static.install(app, dist)
    return TestClient(app)


def test_root_serves_index_without_caching(site: TestClient) -> None:
    res = site.get("/")
    assert res.status_code == 200
    assert res.text == INDEX
    assert res.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path", ["/meme/doomer", "/trace", "/related", "/meme/a/b"])
def test_client_routes_fall_back_to_index(site: TestClient, path: str) -> None:
    res = site.get(path)
    assert res.status_code == 200
    assert res.text == INDEX


def test_hashed_assets_are_immutable(site: TestClient) -> None:
    res = site.get("/assets/index-abc123.js")
    assert res.status_code == 200
    assert res.text == "console.log(1)"
    assert "immutable" in res.headers["cache-control"]


def test_other_files_revalidate(site: TestClient) -> None:
    res = site.get("/favicon.svg")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-cache"


def test_missing_file_is_a_404_not_the_page(site: TestClient) -> None:
    assert site.get("/assets/index-old999.js").status_code == 404


def test_api_routes_win_and_unknown_api_paths_stay_404(site: TestClient) -> None:
    assert site.get("/api/ping").json() == {"ok": True}
    assert site.get("/api/nope").status_code == 404
    assert site.get("/api").status_code == 404
    assert "<title>" not in site.get("/api/nope").text


@pytest.mark.parametrize(
    "path", ["/../secret.txt", "/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt"]
)
def test_cannot_read_outside_the_build(site: TestClient, path: str) -> None:
    res = site.get(path)
    assert "outside the build" not in res.text


def test_does_nothing_without_a_build(tmp_path: Path) -> None:
    app = FastAPI()
    assert not static.install(app, tmp_path / "missing")
    assert TestClient(app).get("/").status_code == 404


def test_default_dist_honours_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(static.ENV_NAME, "/app/web")
    assert static.default_dist() == Path("/app/web")


def test_real_app_registers_the_site_last() -> None:
    paths = [getattr(route, "path", "") for route in real_app.routes]
    if "/{path:path}" in paths:
        assert paths[-1] == "/{path:path}"
