"""Imgflip streams through Context.dev's images+html scrape (json format misses images here)."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from memepedia import contextdev
from memepedia.models import Post
from memepedia.sources import Feed, SourceError

_POST_LINK_RE = re.compile(r'href="/(i|gif)/([a-zA-Z0-9]+)"')
_IMAGE_ID_RE = re.compile(r"/(?:\d+/)?([a-zA-Z0-9]+)\.(?:jpg|jpeg|png)$", re.IGNORECASE)
_ALT_SUFFIX_RE = re.compile(r"\s*\|\s*image tagged in.*$", re.IGNORECASE | re.DOTALL)
_SKIP_EXTENSIONS = (".gif", ".mp4", ".webm")


def _stream_url(stream: str) -> str:
    return f"https://imgflip.com/m/{stream}?sort=latest"


def fetch_raw(feed: Feed) -> contextdev.ScrapeResult:
    """Scrape one Imgflip stream for its post images and raw HTML."""
    return contextdev.scrape(
        _stream_url(feed.target),
        formats={"images": True, "html": True},
        label=f"imgflip:{feed.target}",
        max_age_ms=0,
    )


def _image_post_ids(html: str) -> set[str]:
    """Post ids for static-image posts (`/i/<id>`), excluding GIF posts (`/gif/<id>`)."""
    return {post_id for kind, post_id in _POST_LINK_RE.findall(html) if kind == "i"}


def _image_id(url: str) -> str | None:
    match = _IMAGE_ID_RE.search(url.split("?")[0])
    return match.group(1) if match else None


def _template_title(alt: str | None) -> str:
    """The alt text's leading title, before the `| image tagged in ...` tag list."""
    if not alt:
        return ""
    return _ALT_SUFFIX_RE.sub("", alt).strip()


def parse_stream(result: contextdev.ScrapeResult, *, source: str) -> list[Post]:
    """Join `images` entries to `/i/<id>` post links from `html`, skipping GIF/video posts."""
    post_ids = _image_post_ids(result.html or "")
    now = datetime.now(UTC)
    posts: list[Post] = []
    for image in result.images:
        url = str(image.get("url") or "")
        if not url or url.lower().split("?")[0].endswith(_SKIP_EXTENSIONS):
            continue
        image_id = _image_id(url)
        if image_id is None or image_id not in post_ids:
            continue
        posts.append(
            Post(
                platform="imgflip",
                source=source,
                post_url=f"https://imgflip.com/i/{image_id}",
                image_url=url,
                title=_template_title(image.get("alt")),
                author=None,
                posted_at=now,
            )
        )
    return posts


def fetch_imgflip(feed: Feed) -> list[Post]:
    """Fetch the latest posts from an Imgflip stream."""
    result = fetch_raw(feed)
    if not result.images:
        raise SourceError(f"imgflip {feed.target}: no images returned (possibly blocked)")
    posts = parse_stream(result, source=feed.key)
    if not posts:
        raise SourceError(f"imgflip {feed.target}: no post images joined to a link")
    return posts
