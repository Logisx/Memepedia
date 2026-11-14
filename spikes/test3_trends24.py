"""Test 3: trends24.in JSON extraction of trending topics with time buckets."""
from __future__ import annotations

import time
from typing import Any

from common import client, record_credits, save_json

SCHEMA = {
    "type": "object",
    "properties": {
        "time_buckets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": ["string", "null"]},
                    "trends": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
    "required": ["time_buckets"],
}

INSTRUCTIONS = (
    "This page lists trending topics on X (Twitter) grouped into columns by time, each column "
    "headed by a time label (e.g. 'Now', '1 hour ago'). For each time column, return its label "
    "and the ordered list of trend names in it."
)


def main() -> None:
    c = client()
    t0 = time.time()
    resp = c.post(
        "/web/scrape",
        json={
            "url": "https://trends24.in/",
            "formats": {"json": True, "markdown": True},
            "jsonParams": {"schema": SCHEMA, "instructions": INSTRUCTIONS},
        },
    )
    latency = time.time() - t0
    record_credits("trends24", resp, latency)
    data = resp.json()
    save_json("trends24_raw.json", data)
    js = data.get("json") or {}
    buckets = (js.get("data") or {}).get("time_buckets") if js.get("success") else None
    summary = {
        "status": resp.status_code,
        "latency_s": round(latency, 2),
        "credits": resp.headers.get("X-Credits-Used"),
        "json_success": js.get("success"),
        "json_error": js.get("message") if not js.get("success") else None,
        "n_buckets": len(buckets) if buckets else 0,
        "sample": buckets[:2] if buckets else None,
    }
    save_json("test3_summary.json", summary)
    import json as _json

    print(_json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
