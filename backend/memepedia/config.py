"""Settings read from the environment and the repo-level .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / ".data"
PGDATA_DIR = BACKEND_DIR / ".pgdata"
FIXTURES_DIR = REPO_ROOT / "contract" / "fixtures"

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


@dataclass(frozen=True)
class Settings:
    """Everything the backend reads from its environment."""

    database_url: str | None
    local_db_name: str
    contextdev_key: str | None
    gemini_key: str | None
    gemini_model: str
    public_base_url: str | None
    vision_per_tick: int
    vision_min_confidence: float
    auto_traces_per_tick: int


def _first(*names: str) -> str | None:
    return next((value for name in names if (value := os.environ.get(name))), None)


@lru_cache
def get_settings() -> Settings:
    """Load settings once; the .env file never overrides real environment variables."""
    load_dotenv(REPO_ROOT / ".env")
    return Settings(
        database_url=_first("DATABASE_URL"),
        local_db_name=_first("MEMEPEDIA_DB") or "memepedia",
        contextdev_key=_first("CONTEXTDOTDEV_KEY"),
        gemini_key=_first("GEMINI_API_KEY", "GEMINI_KEY"),
        gemini_model=_first("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL,
        public_base_url=_first("PUBLIC_BASE_URL"),
        vision_per_tick=int(_first("VISION_PER_TICK") or 10),
        vision_min_confidence=float(_first("VISION_MIN_CONFIDENCE") or 0.7),
        auto_traces_per_tick=int(_first("AUTO_TRACES_PER_TICK") or 1),
    )
