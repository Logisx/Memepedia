"""Test 2: Imgflip hot/latest feeds, JS-rendered; check parse quality with/without wait."""
from __future__ import annotations

import time
from typing import Any

from common import client, record_credits, save_json, save_sample

SCHEMA = {
    "type": "object",
    "properties": {
        "posts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "image_url": {"type": ["string", "null"]},
                    "post_link": {"type": ["string", "null"]},
                    "template_name": {"type": ["string", "null"]},
                    "timestamp_text": {"type": ["string", "null"]},
                },
            },
        }
    },
    "required": ["posts"],
}

INSTRUCTIONS = (
    "List every meme post shown on this page. For each: image_url (the full image src), "
    "post_link (the link to the post's own page), template_name (the meme template name, "
    "usually found in the image alt text or title attribute), and timestamp_text (any relative "
    "time text like '3 hours ago' shown near the post, else null)."
)


def scrape(c: Any, url: str, label: str, wait_ms: int | None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "url": url,
        "formats": {"markdown": True, "json": True},
        "jsonParams": {"schema": SCHEMA, "instructions": INSTRUCTIONS},
    }
    if wait_ms:
        body["sharedParams"] = {"waitFor": wait_ms, "settleAnimations": True}
    t0 = time.time()
    resp = c.post("/web/scrape", json=body)
    latency = time.time() - t0
    record_credits(label, resp, latency)
    data = resp.json()
    save_json(f"{label}_raw.json", data)
    md = (data.get("markdown") or {}).get("data") or ""
    save_sample(f"{label}_markdown.txt", md)
    js = data.get("json") or {}
    posts = ((js.get("data") or {}).get("posts")) if js.get("success") else None
    posts = posts or []
    with_img = sum(1 for p in posts if p.get("image_url"))
    with_link = sum(1 for p in posts if p.get("post_link"))
    with_template = sum(1 for p in posts if p.get("template_name"))
    with_ts = sum(1 for p in posts if p.get("timestamp_text"))
    return {
        "status": resp.status_code,
        "latency_s": round(latency, 2),
        "credits": resp.headers.get("X-Credits-Used"),
        "json_success": js.get("success"),
        "json_error": js.get("message") if not js.get("success") else None,
        "n_posts": len(posts),
        "n_with_image": with_img,
        "n_with_link": with_link,
        "n_with_template": with_template,
        "n_with_timestamp": with_ts,
        "sample_posts": posts[:3],
        "md_len": len(md),
    }


def main() -> None:
    c = client()
    results = {}
    results["hot_no_wait"] = scrape(c, "https://imgflip.com/?sort=hot", "imgflip_hot_nowait", None)
    results["hot_with_wait"] = scrape(c, "https://imgflip.com/?sort=hot", "imgflip_hot_wait3000", 3000)
    results["latest_with_wait"] = scrape(c, "https://imgflip.com/?sort=latest", "imgflip_latest_wait3000", 3000)
    save_json("test2_summary.json", results)
    import json as _json

    print(_json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
