"""Test 4: verify meme lineage claims via /web/search with markdown content."""
from __future__ import annotations

import re
import time
from typing import Any

from common import client, record_credits, save_json

CLAIMS = [
    {"child": "Doomer", "parent": "Wojak", "short_child": None},
    {"child": "NPC Wojak", "parent": "Wojak", "short_child": "NPC"},
    {"child": "Cheems", "parent": "Doge", "short_child": None},
    {"child": "Swole Doge vs. Cheems", "parent": "Virgin vs. Chad", "short_child": None},
    {"child": "Trollface", "parent": "Rage Comics", "short_child": None},
]


def find_sentence(text: str, child: str, parent: str, short_child: str | None) -> str | None:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    child_terms = [child.lower()]
    if short_child:
        child_terms.append(short_child.lower())
    for sent in sentences:
        low = sent.lower()
        if any(ct in low for ct in child_terms) and parent.lower() in low:
            return sent.strip()
    return None


def check_claim(c: Any, claim: dict[str, Any]) -> dict[str, Any]:
    child, parent, short = claim["child"], claim["parent"], claim["short_child"]
    query = f'"{child}" "{parent}" meme origin'
    t0 = time.time()
    resp = c.post(
        "/web/search",
        json={
            "query": query,
            "numResults": 5,
            "excludeDomains": ["knowyourmeme.com"],
            "markdownOptions": {"enabled": True, "useMainContentOnly": True},
        },
    )
    latency = time.time() - t0
    label = f"verify_{child}".replace(" ", "_").replace(".", "")
    record_credits(label, resp, latency)
    data = resp.json()
    save_json(f"{label}_raw.json", data)
    results = data.get("results") or []
    found_sentence, found_url, used_short = None, None, False
    domains = []
    for r in results:
        url = r.get("url", "")
        domains.append(url.split("/")[2] if "//" in url else url)
        md = (r.get("markdown") or {}).get("markdown") or ""
        sent = find_sentence(md, child, parent, None)
        if sent:
            found_sentence, found_url = sent, url
            break
        if short:
            sent2 = find_sentence(md, child, parent, short)
            if sent2:
                found_sentence, found_url, used_short = sent2, url, True
                break
    return {
        "child": child,
        "parent": parent,
        "query": query,
        "found": found_sentence is not None,
        "sentence": found_sentence,
        "url": found_url,
        "used_short_form": used_short,
        "latency_s": round(latency, 2),
        "credits": resp.headers.get("X-Credits-Used"),
        "n_results": len(results),
        "domains": domains,
    }


def main() -> None:
    c = client()
    results = [check_claim(c, claim) for claim in CLAIMS]
    save_json("test4_summary.json", results)
    n_found = sum(1 for r in results if r["found"])
    print(f"Found {n_found}/5")
    import json as _json

    print(_json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
