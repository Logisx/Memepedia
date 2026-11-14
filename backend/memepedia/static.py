"""Serve the built web app (web/dist) from the API's own origin.

The site is a single-page app with client-side routes (`/meme/doomer`, `/trace`, ...), so any path
that is not a real file answers with `index.html` and the browser router takes over. Paths under
`/api/` never fall through to the site: an unknown one stays a JSON 404.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from memepedia.config import REPO_ROOT

ENV_NAME = "MEMEPEDIA_WEB_DIST"
IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"


def default_dist() -> Path:
    """The build folder: MEMEPEDIA_WEB_DIST if set (Modal), else web/dist in the repo."""
    return Path(os.environ.get(ENV_NAME) or REPO_ROOT / "web" / "dist")


def install(app: FastAPI, dist: Path) -> bool:
    """Add the site's routes to `app`. Does nothing, and returns False, if `dist` has no build."""
    root = dist.resolve()
    index = root / "index.html"
    if not index.is_file():
        return False

    def page(path: Path, cache: str) -> FileResponse:
        return FileResponse(path, headers={"Cache-Control": cache})

    @app.get("/{path:path}", include_in_schema=False)
    def site(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "No such endpoint.")
        candidate = (root / path).resolve()
        if candidate.is_file() and candidate.is_relative_to(root):
            # Vite names everything under assets/ by content hash, so it never changes.
            cache = IMMUTABLE if candidate.is_relative_to(root / "assets") else REVALIDATE
            return page(candidate, cache)
        if "." in path.rsplit("/", 1)[-1]:
            raise HTTPException(404, "No such file.")
        return page(index, REVALIDATE)

    return True
