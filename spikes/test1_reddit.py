"""Test 1: Reddit through the scraper, three passes ~2min apart, plus RSS/JSON comparison."""
from __future__ import annotations

import re
import time
from typing import Any

from common import client, record_credits, save_json, save_sample

IMG_RE = re.compile(r"(i\.redd\.it|preview\.redd\.it)", re.I)


def scrape_old_reddit(c: Any, pass_no: int) -> dict[str, Any]:
    t0 = time.time()
    resp = c.post(
        "/web/scrape",
        json={
            "url": "https://old.reddit.com/r/memes/new/",
            "formats": {"markdown": True, "html": True},
        },
    )
    latency = time.time() - t0
    record_credits(f"reddit_old_pass{pass_no}", resp, latency)
    body = resp.json()
    save_json(f"reddit_old_pass{pass_no}_raw.json", body)
    markdown = (body.get("markdown") or {}).get("data") or ""
    html = (body.get("html") or {}).get("data") or ""
    posts = parse_posts_from_markdown(markdown)
    save_sample(f"reddit_old_pass{pass_no}_markdown.txt", markdown)
    return {
        "status": resp.status_code,
        "latency_s": round(latency, 2),
        "credits": resp.headers.get("X-Credits-Used"),
        "n_posts_parsed": len(posts),
        "sample_posts": posts[:3],
        "markdown_len": len(markdown),
        "html_len": len(html),
    }


def parse_posts_from_markdown(markdown: str) -> list[dict[str, str]]:
    """Heuristic parse: find blocks with a title line, an image URL, author and age."""
    posts = []
    # Split on common old.reddit markdown post separators (links to comments)
    lines = markdown.splitlines()
    current_img = None
    for i, line in enumerate(lines):
        img_match = IMG_RE.search(line)
        if img_match:
            current_img = line.strip()
        # author pattern: "submitted ... by <author>" or "u/<author>"
        if re.search(r"\bby\s+\[?u/|submitted\s+\d+.*by", line, re.I) or "u/" in line:
            window = lines[max(0, i - 8) : i + 1]
            title_line = next((l for l in reversed(window[:-1]) if len(l.strip()) > 15 and "[" in l), None)
            ts_match = None
            for w in window:
                m = re.search(r"\b(\d+\s+(hour|minute|day|month|year)s?\s+ago)\b", w, re.I)
                if m:
                    ts_match = m.group(1)
            author_match = re.search(r"u/([A-Za-z0-9_-]+)", line)
            if title_line and current_img and author_match:
                posts.append(
                    {
                        "title": title_line.strip()[:80],
                        "author": author_match.group(1),
                        "timestamp": ts_match or "",
                        "image_url_line": current_img[:120],
                    }
                )
    return posts


def scrape_rss(c: Any) -> dict[str, Any]:
    t0 = time.time()
    resp = c.post(
        "/web/scrape",
        json={"url": "https://www.reddit.com/r/memes/new/.rss", "formats": {"markdown": True, "html": True}},
    )
    latency = time.time() - t0
    record_credits("reddit_rss", resp, latency)
    body = resp.json()
    save_json("reddit_rss_raw.json", body)
    html = (body.get("html") or {}).get("data") or ""
    md = (body.get("markdown") or {}).get("data") or ""
    save_sample("reddit_rss_html.txt", html)
    n_entries = html.count("<entry>") if html else md.count("](https://www.reddit.com/r/memes/comments/")
    return {"status": resp.status_code, "latency_s": round(latency, 2), "n_entries_guess": n_entries,
            "md_len": len(md), "html_len": len(html)}


def scrape_json(c: Any) -> dict[str, Any]:
    t0 = time.time()
    resp = c.post(
        "/web/scrape",
        json={"url": "https://www.reddit.com/r/memes/new.json?limit=50", "formats": {"markdown": True}},
    )
    latency = time.time() - t0
    record_credits("reddit_json_endpoint", resp, latency)
    body = resp.json()
    save_json("reddit_json_endpoint_raw.json", body)
    md = (body.get("markdown") or {}).get("data") or ""
    save_sample("reddit_json_endpoint_markdown.txt", md)
    # Try to find the actual JSON payload embedded
    n_children = md.count('"kind": "t3"') if md else 0
    return {"status": resp.status_code, "latency_s": round(latency, 2), "md_len": len(md), "n_children_guess": n_children}


def main() -> None:
    c = client()
    results: dict[str, Any] = {"old_reddit_passes": []}
    for pass_no in range(1, 4):
        results["old_reddit_passes"].append(scrape_old_reddit(c, pass_no))
        if pass_no < 3:
            print("sleeping 120s before next pass...")
            time.sleep(120)
    results["rss"] = scrape_rss(c)
    results["json_endpoint"] = scrape_json(c)
    save_json("test1_summary.json", results)
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    import json

    main()
