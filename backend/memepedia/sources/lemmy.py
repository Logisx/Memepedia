"""Lemmy communities through the direct JSON API, no Context.dev involved."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from memepedia.models import Post
from memepedia.sources import Feed, SourceError

USER_AGENT = "memepedia-archive/0.1 (hackathon research project)"
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def _instance_and_community(target: str) -> tuple[str, str]:
    """Split a `Feed.target` like `lemmy.world/memes` into instance and community."""
    instance, _, community = target.partition("/")
    if not instance or not community:
        raise SourceError(f"bad lemmy feed target {target!r}")
    return instance, community


def _is_image_post(post: dict[str, Any]) -> bool:
    url = (post.get("url") or "").lower().split("?")[0]
    content_type = post.get("url_content_type") or ""
    return url.endswith(IMAGE_EXTENSIONS) or content_type.startswith("image/")


def _is_clean(post: dict[str, Any]) -> bool:
    return not (
        post.get("nsfw")
        or post.get("removed")
        or post.get("deleted")
        or post.get("featured_community")
        or post.get("featured_local")
    )


def _parse_published(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def fetch_raw(instance: str, community: str, *, sort: str, page: int) -> dict[str, Any]:
    """Fetch one page of `/api/v3/post/list` for a community."""
    url = f"https://{instance}/api/v3/post/list"
    params: dict[str, str | int] = {
        "community_name": community,
        "sort": sort,
        "limit": 50,
        "page": page,
    }
    try:
        resp = httpx.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=20.0)
    except httpx.HTTPError as exc:
        raise SourceError(f"lemmy {instance}/{community}: {exc}") from exc
    if resp.status_code != 200:
        raise SourceError(f"lemmy {instance}/{community}: HTTP {resp.status_code}")
    data: dict[str, Any] = resp.json()
    return data


def parse_posts(data: dict[str, Any], *, source: str) -> list[Post]:
    """Keep non-NSFW, non-removed, non-deleted image posts from one list response."""
    posts: list[Post] = []
    for item in data.get("posts") or []:
        post = item.get("post") or {}
        if not (_is_image_post(post) and _is_clean(post)):
            continue
        creator = item.get("creator") or {}
        posts.append(
            Post(
                platform="lemmy",
                source=source,
                post_url=post["ap_id"],
                image_url=post["url"],
                title=post.get("name") or "",
                author=creator.get("name"),
                posted_at=_parse_published(post["published"]),
            )
        )
    return posts


def fetch_lemmy(feed: Feed, *, sort: str = "New", pages: int = 1) -> list[Post]:
    """Fetch image posts from a Lemmy community, newest first, across `pages` pages."""
    instance, community = _instance_and_community(feed.target)
    posts: list[Post] = []
    for page in range(1, pages + 1):
        data = fetch_raw(instance, community, sort=sort, page=page)
        posts.extend(parse_posts(data, source=feed.key))
    return posts
