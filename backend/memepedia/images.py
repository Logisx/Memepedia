"""Image lookup for archive nodes: Imgflip template search first, Wikipedia summary as fallback."""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from typing import Any

import httpx
from rapidfuzz import fuzz

USER_AGENT = "memepedia-archive/0.1 (hackathon research project)"
_MATCH_THRESHOLD = 85.0
_BOX_RE = re.compile(
    r'<div class="mt-box">\s*<h3 class="mt-title">\s*'
    r'<a title="([^"]+?) Meme" href="(/meme/\d+/[^"]+)">.*?'
    r'<img[^>]+src="([^"]+)"',
    re.DOTALL,
)


def _imgflip_search(query: str) -> list[tuple[str, str, str]]:
    """Title, template href and image src for every box on an Imgflip search results page."""
    resp = httpx.get(
        "https://imgflip.com/memesearch",
        params={"q": query},
        headers={"User-Agent": USER_AGENT},
        timeout=20.0,
    )
    if resp.status_code != 200:
        return []
    return [
        (html.unescape(title), href, src if src.startswith("http") else f"https:{src}")
        for title, href, src in _BOX_RE.findall(resp.text)
    ]


def _best_match(
    query: str, candidates: Sequence[tuple[str, str, str]]
) -> tuple[str, str, str] | None:
    scored = [
        (fuzz.token_sort_ratio(query.lower(), title.lower()), title, href, src)
        for title, href, src in candidates
    ]
    if not scored:
        return None
    score, title, href, src = max(scored, key=lambda row: row[0])
    return (title, href, src) if score >= _MATCH_THRESHOLD else None


def _imgflip_lookup(name: str, aliases: Sequence[str]) -> tuple[str, str] | None:
    for query in (name, *aliases):
        match = _best_match(query, _imgflip_search(query))
        if match is None:
            continue
        _title, href, src = match
        return src, f"https://imgflip.com{href}"
    return None


def _wikipedia_lookup(name: str, aliases: Sequence[str]) -> tuple[str, str] | None:
    for query in (name, *aliases):
        title = query.strip().replace(" ", "_")
        resp = httpx.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}",
            headers={"User-Agent": USER_AGENT},
            timeout=15.0,
        )
        if resp.status_code != 200:
            continue
        body = resp.json()
        extract = (body.get("extract") or "").lower()
        thumbnail = (body.get("thumbnail") or {}).get("source")
        page_url = (body.get("content_urls") or {}).get("desktop", {}).get("page")
        if thumbnail and page_url and "meme" in extract:
            return thumbnail, page_url
    return None


def find_image(name: str, aliases: Sequence[str] = ()) -> tuple[str, str] | None:
    """Find an image for a meme name: `(image_url, credit_page_url)`, or `None`."""
    return _imgflip_lookup(name, aliases) or _wikipedia_lookup(name, aliases)


def top_templates() -> list[dict[str, str]]:
    """Imgflip's public top-100 template list, for seeding the archive."""
    resp = httpx.get("https://api.imgflip.com/get_memes", timeout=15.0)
    resp.raise_for_status()
    body = resp.json()
    memes: list[dict[str, Any]] = body.get("data", {}).get("memes", [])
    return [
        {
            "id": meme["id"],
            "name": meme["name"],
            "url": meme["url"],
            "credit_url": f"https://imgflip.com/meme/{meme['id']}",
        }
        for meme in memes
    ]
