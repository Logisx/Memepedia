"""Shared helpers for Context.dev spike scripts. Never print the API key."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

BASE_URL = "https://api.context.dev/v1"
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(__file__).resolve().parent / "out"
CREDITS_LOG = OUT_DIR / "credits_log.jsonl"


def load_key() -> str:
    load_dotenv(ROOT / ".env")
    key = os.environ.get("CONTEXTDOTDEV_KEY")
    if not key:
        raise RuntimeError("CONTEXTDOTDEV_KEY not set in .env")
    return key


def client() -> httpx.Client:
    key = load_key()
    return httpx.Client(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        timeout=60.0,
    )


def record_credits(label: str, resp: httpx.Response, latency_s: float) -> dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    credits_used = resp.headers.get("X-Credits-Used")
    entry = {
        "label": label,
        "status": resp.status_code,
        "credits_used_header": credits_used,
        "latency_s": round(latency_s, 3),
        "ts": time.time(),
    }
    with CREDITS_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"[{label}] status={resp.status_code} credits={credits_used} latency={latency_s:.2f}s")
    return entry


def save_sample(name: str, content: str, limit: int = 3000) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    path.write_text(content[:limit])
    return path


def save_json(name: str, obj: Any) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    path.write_text(json.dumps(obj, indent=2, default=str)[:20000])
    return path


def total_credits() -> float:
    if not CREDITS_LOG.exists():
        return 0.0
    total = 0.0
    for line in CREDITS_LOG.read_text().splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        val = entry.get("credits_used_header")
        try:
            total += float(val)
        except (TypeError, ValueError):
            pass
    return total
