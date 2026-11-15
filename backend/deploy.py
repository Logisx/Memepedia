"""Modal deployment: the public API and site, plus a one-minute clock for the live loop.

The web app (`web/dist`) is baked into the image and served by the API on the same URL, so build
it first. `deploy.ps1` in this folder does both steps; by hand, from the repo root:

    cd web; npm ci; $env:VITE_API_BASE = ""; npm run build; cd ../backend
    uv run --with modal modal deploy deploy.py

The empty `VITE_API_BASE` matters: it overrides web/.env.local, so the site calls the API on its
own origin instead of a hardcoded URL. `deploy.ps1` sets it for you.

Any other app name deploys the frozen staging copy (its own URL, no warm container, no clock);
delete it with `modal app stop memepedia-staging`:

    $env:MEMEPEDIA_APP = "memepedia-staging"

The staging copy is read-only by construction: its secret holds only its own database
(STAGING_DATABASE_URL, else the `memepedia_staging` database next to DATABASE_URL; refused if it
is production's) and MEMEPEDIA_READ_ONLY=1, and no Context.dev or Gemini key at all. Fill that
database with `scripts/clone_db.py` first; see claude_docs/plans/2026-11-14_staging-backup_plan.md.

The values the backend needs are read from the repo's `.env` on this machine at deploy time and
sent to Modal as a Secret. Only the names in `SENT` leave the machine; the database must be a
hosted one (`DATABASE_URL`), because the local development database does not exist on Modal.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import modal

SENT = (
    "DATABASE_URL",
    "CONTEXTDOTDEV_KEY",
    "GEMINI_KEY",
    "GEMINI_MODEL",
    "GUARDRAIL_MODEL",
    "PUBLIC_BASE_URL",
    "CONTEXTDEV_WEBHOOK_SECRET",
    "VISION_MIN_CONFIDENCE",
    "VISION_EXACT_MIN_CONFIDENCE",
    "VISION_MATCH_SUBJECTS",
    # Cost guards and the clock fallback (memepedia/budget.py, live.clock_tick).
    "VISION_PER_TICK",
    "AUTO_TRACES_PER_TICK",
    "MEMEPEDIA_PAID_OFF",
    "MEMEPEDIA_CAP_CONTEXTDEV",
    "MEMEPEDIA_CAP_GEMINI",
    "MEMEPEDIA_CAP_TRACES",
    "MEMEPEDIA_CLOCK_FALLBACK_MINUTES",
)
REQUIRED = ("DATABASE_URL", "CONTEXTDOTDEV_KEY", "GEMINI_KEY")
CLOCK_MINUTES = 1
APP_NAME = os.environ.get("MEMEPEDIA_APP") or "memepedia"
LIVE = APP_NAME == "memepedia"
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
WEB_DIST_IN_IMAGE = "/app/web"


def _dotenv(path: Path) -> dict[str, str]:
    lines = (line.strip().removeprefix("export ") for line in path.read_text().splitlines())
    pairs = (line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))
    return {key.strip(): value.strip().strip("'\"") for key, value in pairs}


def _secret() -> modal.Secret:
    if not modal.is_local():
        return modal.Secret.from_dict({})
    values = _dotenv(Path(__file__).resolve().parent.parent / ".env")
    if not LIVE:
        return modal.Secret.from_dict(_staging_values(values))
    missing = [name for name in REQUIRED if not values.get(name)]
    if missing:
        raise SystemExit(f"Add {', '.join(missing)} to .env before deploying.")
    return modal.Secret.from_dict({name: values[name] for name in SENT if values.get(name)})


def _staging_values(values: dict[str, str]) -> dict[str, str]:
    """The staging copy's whole secret: its own database, read-only, and no paid API key."""
    from memepedia.staging import describe, resolve_staging_url, same_database

    merged = {**values, **os.environ}
    url = resolve_staging_url(merged)
    if not url:
        raise SystemExit("Set DATABASE_URL or STAGING_DATABASE_URL in .env first.")
    if any(same_database(url, env.get("DATABASE_URL")) for env in (values, merged)):
        raise SystemExit("The staging database is production's; refusing to deploy over it.")
    print(f"Staging copy reads {describe(url)}, read-only, with no Context.dev or Gemini key.")
    return {"DATABASE_URL": url, "MEMEPEDIA_READ_ONLY": "1"}


def _clock_enabled() -> bool:
    """Whether the live-loop clock is scheduled on Modal. Off unless MEMEPEDIA_CLOCK is truthy.

    Checked at deploy time only (a schedule is set when the app is deployed, not per-container),
    first from the shell environment, then from `.env`. Never on a staging copy of the app, so two
    clocks cannot work the same database.
    """
    if not modal.is_local() or not LIVE:
        return False
    value = os.environ.get("MEMEPEDIA_CLOCK")
    if value is None:
        value = _dotenv(Path(__file__).resolve().parent.parent / ".env").get("MEMEPEDIA_CLOCK")
    return (value or "").strip().lower() in {"1", "true", "on", "yes"}


def _web_dist() -> Path:
    if not modal.is_local():
        return WEB_DIST
    if not (WEB_DIST / "index.html").is_file():
        raise SystemExit(f"Build the web app first (deploy.ps1 does it): no {WEB_DIST}.")
    for bundle in (WEB_DIST / "assets").glob("*.js"):
        if ".modal.run" in bundle.read_text(encoding="utf-8", errors="ignore"):
            raise SystemExit(
                f"{bundle.name} has a hardcoded backend URL (web/.env.local?). "
                "Rebuild with VITE_API_BASE empty (deploy.ps1 does it)."
            )
    return WEB_DIST


app = modal.App(APP_NAME)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_sync()
    .env({"MEMEPEDIA_WEB_DIST": WEB_DIST_IN_IMAGE})
    .add_local_python_source("memepedia", ignore=["**/__pycache__/**", "**/*.pyc"])
    .add_local_dir(_web_dist(), WEB_DIST_IN_IMAGE)
)
secret = _secret()
clock_schedule = modal.Period(minutes=CLOCK_MINUTES) if _clock_enabled() else None


@app.function(
    image=image,
    secrets=[secret],
    min_containers=1 if LIVE else 0,
    scaledown_window=300,
    timeout=600,
)
@modal.concurrent(max_inputs=50)
@modal.asgi_app()
def web() -> Any:
    """The FastAPI app and the built site, kept warm so the wall never waits on a cold start."""
    from memepedia.api import app as api

    return api


@app.function(image=image, secrets=[secret], schedule=clock_schedule, timeout=240)
def clock() -> None:
    """Visit one feed per run, in rotation, as the fallback to the Context.dev monitor webhooks.

    Paused by default: deploy with `MEMEPEDIA_CLOCK=1` (env var or `.env`) to schedule it, and
    with that unset or falsy to redeploy it unscheduled (the function stays callable by hand,
    it just does not run on a timer). When scheduled it stays idle while monitor webhooks keep
    arriving, and goes through the same cost guards as they do (`live.clock_tick`).
    """
    from memepedia import live
    from memepedia.sources import FEEDS

    turn = int(time.time() // (60 * CLOCK_MINUTES)) % len(FEEDS)
    print(live.clock_tick(FEEDS[turn].key))
