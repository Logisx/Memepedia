"""Shared predicate for sources this archive must never cite.

Know Your Meme's terms forbid aggregation, so the archive refuses its pages even when they are
reached indirectly: a Reddit post or any other page whose title or text identifies it as a Know
Your Meme page (or a mirror of one) is refused in exactly the same way as a direct
knowyourmeme.com URL. Checking the URL's host alone is not enough, since a quote and title can be
lifted from a page that merely repeats a Know Your Meme page's own title or content.
"""

from __future__ import annotations

import re

_BLOCKED_RE = re.compile(r"know[\s-]*your[\s-]*meme|kym-cdn", re.IGNORECASE)


def is_blocked(*parts: str | None) -> bool:
    """True when any of `parts` mentions a blocked source, case-insensitively.

    Matches "knowyourmeme", "know your meme" and "know-your-meme" alike, since a quote or title
    can name the site in prose rather than in a URL."""
    return any(part and _BLOCKED_RE.search(part) for part in parts)
