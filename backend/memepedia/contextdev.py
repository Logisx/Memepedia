"""Thin client for the Context.dev API (https://api.context.dev/v1), Bearer-auth, sync httpx.

Covers `/web/scrape`, `/web/search` and `/monitors`. Plain HTTP in, typed objects out: this
module never logs the API key, and touches the database only through `budget`, which refuses a
paid call once the Context.dev credit cap or the kill switch says so and records what each call
spent.

Monitor webhooks (from the docs; never exercised live by the spikes): creating a monitor with
`webhook: {"url": ..., "retry": {...}}` makes Context.dev POST events to that URL. `retry: {}`
means one attempt plus one quick retry on a network error, 429 or 5xx; a non-empty `delays` list
(up to 10 values, 1-86400s each, 72h total) schedules more retries, an empty list disables them.
Each delivery carries `X-Context-Event` (the event name), `X-Context-Id` (stable per logical
event, same across retries/replays), `X-Context-Delivery-Id` (unique per attempt),
`X-Context-Attempt`, and `X-Context-Signature: t=<unix_ts>,v1=<hex hmac-sha256 of "t.rawBody"
using the whsec_... secret>`. Event bodies: `run.completed` -> `{id, data: {run: <run object>,
change: <change object> | null}}`; `change.detected` -> `{id, data: {change: <change object>}}`.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from memepedia import blocklist, budget, config

BASE_URL = "https://api.context.dev/v1"
_RETRYABLE_STATUS = {500, 502, 503, 504}
_ledger_lock = threading.Lock()
log = logging.getLogger("memepedia.contextdev")


class ContextDevError(Exception):
    """Base error for a failed Context.dev call; carries the HTTP status and API message."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class Blocked(ContextDevError):
    """The target site served an anti-bot challenge or access wall instead of its page."""


class CreditCapReached(ContextDevError):
    """The credit cap or the kill switch refuses any further paid Context.dev call."""


class MissingKey(ContextDevError):
    """No Context.dev API key is configured."""

    def __init__(self) -> None:
        super().__init__("CONTEXTDOTDEV_KEY is not configured")


@dataclass(frozen=True)
class ScrapeResult:
    """What `/web/scrape` returned for the requested formats."""

    url: str
    title: str | None
    markdown: str | None
    html: str | None
    images: list[dict[str, Any]]
    credits: float


@dataclass(frozen=True)
class SearchHit:
    """One `/web/search` result with its page content inlined as markdown."""

    url: str
    title: str | None
    markdown: str | None


def _client(timeout: float) -> httpx.Client:
    key = config.get_settings().contextdev_key
    if not key:
        raise MissingKey
    return httpx.Client(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        timeout=timeout,
    )


def _request(
    method: str, path: str, *, json_body: Mapping[str, Any] | None, timeout: float
) -> httpx.Response:
    with _client(timeout) as http:
        for attempt in (1, 2):
            try:
                resp = http.request(method, path, json=json_body)
            except httpx.TimeoutException:
                if attempt == 2:
                    raise ContextDevError(f"{method} {path} timed out") from None
                continue
            if resp.status_code in _RETRYABLE_STATUS and attempt == 1:
                continue
            return resp
    raise ContextDevError(f"{method} {path} failed with no response")


def _guard(what: str) -> None:
    """Raise `CreditCapReached` when the budget allows no more paid Context.dev work."""
    reason = budget.block_reason("contextdev")
    if reason is not None:
        raise CreditCapReached(f"{what} refused: {reason}")


def _charge(credits: float) -> None:
    try:
        budget.charge("contextdev", credits)
    except Exception:  # the call already happened; losing its record must not lose its result
        log.exception("could not record %s Context.dev credits", credits)


def _record_credit(
    endpoint: str, label: str, credits: float, latency_s: float, status: int
) -> None:
    _charge(credits)
    entry = {
        "ts": time.time(),
        "endpoint": endpoint,
        "label": label,
        "credits": credits,
        "latency_s": round(latency_s, 3),
        "status": status,
    }
    path = config.DATA_DIR / "credits.jsonl"
    with _ledger_lock:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(entry) + "\n")


def credits_spent() -> float:
    """Sum every credit amount ever recorded in the ledger."""
    path = config.DATA_DIR / "credits.jsonl"
    if not path.exists():
        return 0.0
    total = 0.0
    for line in path.read_text().splitlines():
        if line.strip():
            total += float(json.loads(line).get("credits") or 0.0)
    return total


def _header_credits(resp: httpx.Response) -> float:
    try:
        return float(resp.headers.get("X-Credits-Used", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _raise_for_status(resp: httpx.Response, context: str) -> None:
    if resp.is_success:
        return
    try:
        message = resp.json().get("message", resp.text)
    except ValueError:
        message = resp.text
    raise ContextDevError(f"{context}: {message}", status=resp.status_code)


def blocked_message(body: Mapping[str, Any]) -> str | None:
    """The block message if any requested format reports `error_code == "WEBSITE_BLOCKED"`."""
    for key in ("markdown", "html", "json", "images", "screenshot"):
        block = body.get(key)
        if isinstance(block, Mapping) and block.get("error_code") == "WEBSITE_BLOCKED":
            return str(block.get("message") or "WEBSITE_BLOCKED")
    return None


def scrape(
    url: str,
    *,
    formats: Mapping[str, Any],
    label: str,
    timeout: float = 60.0,
    max_age_ms: int | None = None,
) -> ScrapeResult:
    """Scrape one URL through `/web/scrape`, raising `Blocked` if the site walled the request.

    `max_age_ms` caps how old a cached output Context.dev may hand back (its own default is
    259200000 ms, three days); pass `0` for a guaranteed-fresh capture, as every live feed fetch
    does, since otherwise a feed can keep serving the same stale snapshot for hours.
    """
    if blocklist.is_blocked(url):
        raise ContextDevError("knowyourmeme.com may not be scraped (its terms forbid aggregation)")
    _guard(f"scrape {url}")
    t0 = time.time()
    body: dict[str, Any] = {"url": url, "formats": dict(formats)}
    if max_age_ms is not None:
        body["maxAgeMs"] = max_age_ms
    resp = _request("POST", "/web/scrape", json_body=body, timeout=timeout)
    latency = time.time() - t0
    credits = _header_credits(resp)
    _record_credit("/web/scrape", label, credits, latency, resp.status_code)
    _raise_for_status(resp, f"scrape {url}")
    body = resp.json()
    blocked = blocked_message(body)
    if blocked:
        raise Blocked(f"scrape {url} blocked: {blocked}")
    markdown_block = body.get("markdown") or {}
    html_block = body.get("html") or {}
    images_block = body.get("images") or {}
    metadata = body.get("metadata") or {}
    return ScrapeResult(
        url=body.get("url") or url,
        title=metadata.get("title"),
        markdown=markdown_block.get("data"),
        html=html_block.get("data"),
        images=list(images_block.get("data") or []),
        credits=credits,
    )


def search(
    query: str,
    *,
    num_results: int = 5,
    exclude_domains: Sequence[str] = ("knowyourmeme.com", "kym-cdn.com"),
    label: str,
    timeout: float = 60.0,
) -> list[SearchHit]:
    """Search the web through `/web/search`, with page content inlined as markdown."""
    _guard(f"search {query!r}")
    t0 = time.time()
    body = {
        "query": query,
        "numResults": num_results,
        "excludeDomains": list(exclude_domains),
        "markdownOptions": {"enabled": True, "useMainContentOnly": True},
    }
    resp = _request("POST", "/web/search", json_body=body, timeout=timeout)
    latency = time.time() - t0
    credits = _header_credits(resp)
    _record_credit("/web/search", label, credits, latency, resp.status_code)
    _raise_for_status(resp, f"search {query!r}")
    return parse_search_hits(resp.json())


def parse_search_hits(body: Mapping[str, Any]) -> list[SearchHit]:
    """Turn a `/web/search` response body into its `SearchHit` list."""
    hits = []
    for r in body.get("results") or []:
        md = (r.get("markdown") or {}).get("markdown")
        hits.append(SearchHit(url=r.get("url", ""), title=r.get("title"), markdown=md))
    return hits


def _monitor_credits(body: Mapping[str, Any]) -> float:
    meta = body.get("key_metadata") or {}
    try:
        return float(meta.get("credits_consumed") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def create_monitor(
    name: str, url: str, *, minutes: int = 10, webhook_url: str | None = None
) -> dict[str, Any]:
    """Create a page monitor polling `url` every `minutes` (minimum 10).

    With a webhook, every run (not only a changed one) is delivered as `run.completed`, so the
    receiver can count each run's credits and knows the monitors are alive. Creation queues a
    baseline run, which costs a credit, so it is refused when the budget is spent.
    """
    _guard(f"create_monitor {name!r}")
    body: dict[str, Any] = {
        "name": name,
        "target": {"type": "page", "url": url},
        "schedule": {"type": "interval", "frequency": minutes, "unit": "minutes"},
    }
    if webhook_url:
        body["webhook"] = {"url": webhook_url, "events": ["run.completed"]}
    t0 = time.time()
    resp = _request("POST", "/monitors", json_body=body, timeout=30.0)
    data = resp.json()
    latency = time.time() - t0
    _record_credit("/monitors", "create_monitor", _monitor_credits(data), latency, resp.status_code)
    _raise_for_status(resp, f"create_monitor {name!r}")
    return dict(data)


def list_monitors() -> list[dict[str, Any]]:
    """List every configured monitor."""
    t0 = time.time()
    resp = _request("GET", "/monitors", json_body=None, timeout=30.0)
    data = resp.json()
    latency = time.time() - t0
    _record_credit("/monitors", "list_monitors", _monitor_credits(data), latency, resp.status_code)
    _raise_for_status(resp, "list_monitors")
    return list(data.get("data") or [])


def run_monitor(monitor_id: str) -> dict[str, Any]:
    """Trigger an on-demand run; a no-op if the previous run is still in flight."""
    _guard(f"run_monitor {monitor_id}")
    t0 = time.time()
    resp = _request("POST", f"/monitors/{monitor_id}/run", json_body=None, timeout=30.0)
    data = resp.json()
    latency = time.time() - t0
    _record_credit("/monitors", "run_monitor", _monitor_credits(data), latency, resp.status_code)
    _raise_for_status(resp, f"run_monitor {monitor_id}")
    return dict(data)


def _monitor_call(method: str, path: str, body: Mapping[str, Any] | None) -> dict[str, Any]:
    """One free monitor-management call, ledgered like the others; raises on an API error."""
    t0 = time.time()
    resp = _request(method, path, json_body=body, timeout=30.0)
    data = resp.json()
    _record_credit("/monitors", path, _monitor_credits(data), time.time() - t0, resp.status_code)
    _raise_for_status(resp, f"{method} {path}")
    return dict(data)


def set_monitor_status(monitor_id: str, status: str) -> dict[str, Any]:
    """Pause (`"paused"`) or resume (`"active"`) a monitor; a paused one runs and costs nothing."""
    return _monitor_call("PATCH", f"/monitors/{monitor_id}", {"status": status})


def rotate_webhook_secret(monitor_id: str) -> str | None:
    """Issue a new webhook signing secret for a monitor and return it; the old one stops working."""
    data = _monitor_call("POST", f"/monitors/{monitor_id}/webhook/rotate-secret", None)
    return webhook_secret_of(data)


def webhook_secret_of(body: Mapping[str, Any]) -> str | None:
    """The `whsec_...` signing secret in a monitor response, wherever the API put it."""
    webhook = body.get("webhook")
    secret = webhook.get("secret") if isinstance(webhook, Mapping) else None
    secret = secret or body.get("secret")
    return str(secret) if secret else None


def delete_monitor(monitor_id: str) -> bool:
    """Delete a monitor; returns whether the API confirmed deletion."""
    t0 = time.time()
    resp = _request("DELETE", f"/monitors/{monitor_id}", json_body=None, timeout=30.0)
    data = resp.json()
    latency = time.time() - t0
    _record_credit("/monitors", "delete_monitor", _monitor_credits(data), latency, resp.status_code)
    _raise_for_status(resp, f"delete_monitor {monitor_id}")
    return bool(data.get("deleted"))
