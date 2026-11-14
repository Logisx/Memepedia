"""Reddit subreddits through Context.dev's RSS scrape (old.reddit.com and .json are walled)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from xml.etree import ElementTree as ET

from memepedia import contextdev
from memepedia.models import Post
from memepedia.sources import Feed, SourceError

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
_FULL_IMAGE_RE = re.compile(r'href="(https://i\.redd\.it/[^"]+)"')
_PREVIEW_IMAGE_RE = re.compile(r'<img src="(https://preview\.redd\.it/[^"]+)"')


def _feed_url(subreddit: str) -> str:
    return f"https://www.reddit.com/r/{subreddit}/new/.rss"


def fetch_raw(feed: Feed) -> str:
    """Scrape one subreddit's new-posts Atom feed through Context.dev."""
    result = contextdev.scrape(
        _feed_url(feed.target),
        formats={"markdown": True, "html": True},
        label=f"reddit:{feed.target}",
        max_age_ms=0,
    )
    xml_text = result.html or result.markdown
    if not xml_text:
        raise SourceError(f"reddit {feed.target}: empty scrape response")
    return xml_text


def _entry_image(content_html: str) -> str | None:
    full = _FULL_IMAGE_RE.search(content_html)
    if full:
        return full.group(1)
    preview = _PREVIEW_IMAGE_RE.search(content_html)
    return preview.group(1) if preview else None


def _entry_post(entry: ET.Element, *, source: str) -> Post | None:
    content_el = entry.find("atom:content", ATOM_NS)
    content_html = content_el.text or "" if content_el is not None else ""
    image_url = _entry_image(content_html)
    if not image_url:
        return None
    link_el = entry.find("atom:link", ATOM_NS)
    title_el = entry.find("atom:title", ATOM_NS)
    published_el = entry.find("atom:published", ATOM_NS)
    if link_el is None or title_el is None or published_el is None or not published_el.text:
        return None
    author_el = entry.find("atom:author/atom:name", ATOM_NS)
    author = (author_el.text or "").removeprefix("/u/") if author_el is not None else None
    return Post(
        platform="reddit",
        source=source,
        post_url=link_el.get("href", ""),
        image_url=image_url,
        title=title_el.text or "",
        author=author or None,
        posted_at=_parse_timestamp(published_el.text),
    )


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_atom(xml_text: str, *, source: str) -> list[Post]:
    """Parse a subreddit's Atom feed into its image posts."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceError(f"reddit {source}: unparsable feed ({exc})") from exc
    posts = []
    for entry in root.findall("atom:entry", ATOM_NS):
        post = _entry_post(entry, source=source)
        if post is not None:
            posts.append(post)
    return posts


def fetch_reddit(feed: Feed) -> list[Post]:
    """Fetch new image posts from a subreddit via its Atom feed."""
    xml_text = fetch_raw(feed)
    posts = parse_atom(xml_text, source=feed.key)
    if not posts:
        raise SourceError(f"reddit {feed.target}: zero parsable entries (possibly blocked)")
    return posts
