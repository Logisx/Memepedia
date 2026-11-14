"""Modal deployment: the public API and a one-minute clock for the live loop.

Deploy from `backend/` with:

    uv run --with modal modal deploy deploy.py

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
    "PUBLIC_BASE_URL",
    "CONTEXTDEV_WEBHOOK_SECRET",
)
REQUIRED = ("DATABASE_URL", "CONTEXTDOTDEV_KEY", "GEMINI_KEY")
CLOCK_MINUTES = 1


def _dotenv(path: Path) -> dict[str, str]:
    lines = (line.strip().removeprefix("export ") for line in path.read_text().splitlines())
    pairs = (line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))
    return {key.strip(): value.strip().strip("'\"") for key, value in pairs}


def _secret() -> modal.Secret:
    if not modal.is_local():
        return modal.Secret.from_dict({})
    values = _dotenv(Path(__file__).resolve().parent.parent / ".env")
    missing = [name for name in REQUIRED if not values.get(name)]
    if missing:
        raise SystemExit(f"Add {', '.join(missing)} to .env before deploying.")
    return modal.Secret.from_dict({name: values[name] for name in SENT if values.get(name)})


def _clock_enabled() -> bool:
    """Whether the live-loop clock is scheduled on Modal. Off unless MEMEPEDIA_CLOCK is truthy.

    Checked at deploy time only (a schedule is set when the app is deployed, not per-container),
    first from the shell environment, then from `.env`.
    """
    if not modal.is_local():
        return False
    value = os.environ.get("MEMEPEDIA_CLOCK")
    if value is None:
        value = _dotenv(Path(__file__).resolve().parent.parent / ".env").get("MEMEPEDIA_CLOCK")
    return (value or "").strip().lower() in {"1", "true", "on", "yes"}


app = modal.App("memepedia")
image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_sync()
    .add_local_python_source("memepedia", ignore=["**/__pycache__/**", "**/*.pyc"])
)
secret = _secret()
clock_schedule = modal.Period(minutes=CLOCK_MINUTES) if _clock_enabled() else None


@app.function(image=image, secrets=[secret], min_containers=1, scaledown_window=300, timeout=600)
@modal.concurrent(max_inputs=50)
@modal.asgi_app()
def web() -> Any:
    """The FastAPI app, kept warm so the wall never waits on a cold start."""
    from memepedia.api import app as api

    return api


@app.function(image=image, secrets=[secret], schedule=clock_schedule, timeout=240)
def clock() -> None:
    """Visit one feed per run, in rotation; after the last feed, look for emerging memes.

    Paused by default: deploy with `MEMEPEDIA_CLOCK=1` (env var or `.env`) to schedule it, and
    with that unset or falsy to redeploy it unscheduled (the function stays callable by hand,
    it just does not run on a timer).
    """
    from memepedia import live, store
    from memepedia.sources import FEEDS

    turn = int(time.time() // (60 * CLOCK_MINUTES)) % len(FEEDS)
    print(live.tick(FEEDS[turn].key))
    if turn == len(FEEDS) - 1:
        print("specimens:", live.detect_specimens())
        store.expire_specimens()
