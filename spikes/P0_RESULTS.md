# Context.dev spike results — meme-genealogy P0

Scripts in `spikes/` (run via `uv run --with httpx --with python-dotenv python spikes/<name>.py`).
Trimmed samples / raw JSON in `spikes/out/`. Running credit ledger in `spikes/out/credits_log.jsonl`
(one line per request, `X-Credits-Used` header value).

**Total credits spent across all tests: ~55** (well under the 400 budget). `/monitors/*` endpoints do
not set `X-Credits-Used` at all — their cost is reported in the response body's `key_metadata.credits_consumed`
instead (see Test 5).

---

## Test 1 — Reddit through the scraper

**Criterion:** each of 3 passes on `old.reddit.com/r/memes/new/` returns ≥20 posts with title+timestamp+author+image.

**Result: FAIL** on the stated target; the RSS fallback fully compensates.

| Attempt | HTTP | Latency | Credits | Posts parsed |
|---|---|---|---|---|
| old.reddit pass 1 | 200 | 44.6s | (blocked, no charge) | 0 |
| old.reddit pass 2 | 200 | 4.6s | 1 | 0 |
| old.reddit pass 3 | 200 | 0.7s | 1 | 0 |
| `reddit.com/r/memes/new/.rss` | 200 | 2.5s | 1 | 25/25 complete |
| `reddit.com/r/memes/new.json?limit=50` | 200 | 10.7s | (blocked, no charge) | 0 |

**What happened:** every `old.reddit.com` call got HTTP 200 but the scraped page was Reddit's own login
wall ("Para que Reddit sea un sitio seguro, se requiere una cuenta para acceder al Reddit antiguo" —
served in Spanish, so Context.dev's fetch is geo-routed through Spain/EU). Pass 1's response had an explicit
`error_code: "WEBSITE_BLOCKED"` on both `markdown` and `html` with: *"The site served an anti-bot challenge
or access wall instead of the page. Retrying later or from another sharedParams.country sometimes succeeds."*
Passes 2–3 rendered the same login-wall HTML (358KB) without Context.dev flagging it as blocked — i.e. the API
doesn't always detect a soft wall, so **a caller must content-check, not just status-check.** old.reddit.com now
appears to require a logged-in session unconditionally (Reddit-side policy, not a scraper bug); no amount of
the `/web/scrape` options here would get around it except a real authenticated `sharedParams.browserProfile`
(a paid-plan feature we didn't test).

The `.json` endpoint also got `WEBSITE_BLOCKED` — Reddit's own API front door is apparently walled the same way
when hit by Context.dev's fetcher.

The **`.rss` feed worked cleanly**: single `/web/scrape` call, 2.5s, 1 credit, returned valid Atom XML with 25
`<entry>` elements, each carrying `<title>`, `<published>` (ISO timestamp), `<name>/u/author</name>`, and both an
`i.redd.it` full-image link and a `preview.redd.it` thumbnail. All 25/25 entries had all four required fields —
far above the 20-post bar.

**Recommendation for the design:** use the `.rss` form, not `old.reddit.com` scraping or the `.json` endpoint.
It's the cheapest (1 credit), fastest (~2.5s), and most reliable of the three — clean, stable field names, no
JS rendering needed, no bot-wall exposure observed in this run. Budget for retries/backoff anyway in case Reddit
starts walling `.rss` too.

Samples: `spikes/out/reddit_old_pass1_markdown.txt` (shows the Spanish login wall text),
`spikes/out/reddit_rss_html.txt` (first 3000 chars of valid Atom XML), `spikes/out/test1_summary.json`.

---

## Test 2 — Imgflip

**Criterion (informal):** can we parse image URL + post link + template name from the hot/latest feeds; do posts carry timestamps.

**Result: PARTIAL.** Post links and images are reliably extractable; "template name" is not a clean field —
it has to be inferred from an alt-text tag list; no timestamps are exposed on the feed page at all.

| Call | Latency | Credits | Notes |
|---|---|---|---|
| `?sort=hot`, `json` format, no wait | 7–9s | 1 | 14 posts found, 0 with image/template (see below) |
| `?sort=hot`, `json` format, `waitFor: 3000` | 9.6s | 5 | same 14 posts, still 0 with image/template via JSON extraction |
| `?sort=latest`, `json` format, `waitFor: 3000` | 9.0s | 5 | same pattern |
| `?sort=hot`, `images` + `html` formats, `waitFor: 3000` | 5.6s | 1 | **this is the combination that actually works** |

**What happened:**
1. `https://imgflip.com/?sort=hot` 302-redirects to `https://imgflip.com/m/fun` (the "fun" stream) — `?sort=hot`
   on the bare root is not itself a valid listing sort; a design that needs "hot" should hit a stream URL like
   `/m/fun?sort=hot` or `/m/memes?sort=hot`, not the bare homepage.
2. Asking `formats.json` with a schema for `image_url`/`template_name`/`timestamp_text` reliably found the 14
   post links (`/i/<id>` or `/gif/<id>`) but never filled `image_url` or `template_name` — the markdown
   representation Context.dev builds for this JS-heavy page keeps the post title as link text and drops the
   `<img>` tag's `src`/`alt` entirely, so the JSON extractor (which appears to work off the markdown/text
   representation) has nothing to read those from.
3. Switching to `formats: {images: true, html: true}` (1 credit, no `waitFor` needed) got everything: the
   `images` output returned 63 image entries including the real post images
   (`https://i.imgflip.com/2/<id>.jpg`, correlatable to the post links by ID) and raw `html` showed each static
   post's `<img class="base-img" alt="... | image tagged in <tag1,tag2,...> | made w/ Imgflip meme maker">`.
   The `alt` text is **a tag list, not a single template name** — e.g. `alt="...| image tagged in memes,one
   does not simply,funny,cpr,pass away,stank | made w/ Imgflip meme maker"`. Sometimes a tag matches the
   template (`one does not simply`), sometimes it's just topical tags with no template hint at all. GIF posts
   (`<video>` elements, not `<img>`) carry **no alt text whatsoever** — no template signal at all for those.
4. **No timestamps anywhere** on the hot/latest feed pages (searched the full HTML for "ago", "timeago",
   and timestamp-ish class names — none found). Getting a post's age would require visiting each post's own
   page.

**Recommendation for the design:** scrape with `formats: {images: true, html: true}` (skip `json`/`waitFor`,
it's both more expensive and doesn't deliver what's needed), correlate `images[].url` to post links by the
numeric/alnum ID in the URL, and treat "template name" as best-effort from the tag list — don't rely on it for
anything that needs to be exact. If template identity matters for the genealogy graph, the alt-text tags from
the Imgflip *"Meme Templates"* pages (not the feed) would be a cleaner source — not tested here (out of P0 scope).

Samples: `spikes/out/imgflip_images_html_raw.json`, `spikes/out/imgflip_hot_wait3000_markdown.txt`,
`spikes/out/test2_summary.json`.

---

## Test 3 — Trend text (trends24.in)

**Criterion (informal):** clean JSON extraction of trending topics with time buckets, and its cost.

**Result: PASS**, but slow.

- Status 200, **latency 45.75s**, **5 credits**.
- `jsonParams.schema` asking for `time_buckets[].{label, trends[]}` returned **24 time buckets** cleanly, each
  with a plausible label (`"30 minutes ago"`, `"1 hour ago"`, …) and an ordered list of trend strings (mixed
  English/Japanese/Thai/Portuguese — trends24.in aggregates multiple countries' trend columns on one page, so
  design should decide which country columns it actually wants and filter, or pass `includeSelectors`/parsing
  instructions to restrict to one country).
- Extraction was genuinely clean — no null/garbled fields, no sign of truncation at 24 buckets.
- The **45.75s latency is the standout number** for this test: trends24.in is a large, many-column page, and a
  full-page JSON-schema extraction over it is clearly doing non-trivial LLM-side work. For a "live" background
  loop this is too slow to run inline on every refresh tick; it should be called from an async job and cached
  rather than awaited on a request path.

**Recommendation for the design:** works, but budget 45–60s and 5 credits per call; restrict scope (selectors or
tighter instructions, or target a single-country trends24 URL like `trends24.in/united-states/`) to cut both.

Sample: `spikes/out/trends24_raw.json`, `spikes/out/test3_summary.json`.

---

## Test 4 — Verify step (lineage claims via `/web/search`)

**Criterion:** supporting sentence found for ≥3/5 claims.

**Result: PASS — 4/5 found.**

| Claim | Found | Latency | Credits | Domain |
|---|---|---|---|---|
| Doomer ← Wojak | yes | 5.9s | 6 | howtodothingswithmemes.substack.com |
| NPC Wojak ← Wojak | yes | 21.2s | 4 | meme.com |
| Cheems ← Doge | yes | 6.1s | 5 | meme.com |
| Swole Doge vs. Cheems ← Virgin vs. Chad | **no** | 3.4s | 5 | (results from gurus.dedyn.io, mememoe.com, portal.intuition.systems, grokipedia.com, meme.com — none had both exact phrases in one sentence) |
| Trollface ← Rage Comics | yes | 6.1s | 6 | memepulse.net |

One `/web/search` call per claim (`numResults: 5`, `excludeDomains: ["knowyourmeme.com"]`,
`markdownOptions: {enabled: true, useMainContentOnly: true}`) returned markdown content inline in the same
call — no separate scrape needed, confirming the API can do search+content in one shot as the brief hoped.
Per-claim latency was 3–21s (one outlier at 21s, no obvious cause — possibly a slow upstream page in that
result set); credits ran 4–6 per call.

**Caveats on "found":** the sentence-matching here is a naive regex split on `.!?`, and markdown headers (no
terminal punctuation) sometimes got glued to the next sentence, so a couple of the "sentences" above are really
a heading + first sentence concatenated (e.g. the Doomer one is `"# The Evolution of Doomer\n...\nWhen we look
forward..."`). The *support* is real (the right page, on-topic), but production code should strip
headers/front-matter before sentence-splitting, or use the API's `highlightsOptions` (relevant-passage
extraction) instead of rolling a sentence splitter — that's a cleaner fit than what this spike hand-rolled.

The one miss (Swole Doge vs. Cheems / Virgin vs. Chad) is a real content gap in this exact query form, not an
API failure — top-5 results for that compound quoted query didn't converge on a page naming both formats in
one sentence. A follow-up query without the quotes, or two separate claims, would likely do better.

Domains seen across all 5 claims: substack.com, **meme.com** (appeared 2x — a KYM-style aggregator, worth
checking its scrape terms if used at scale), memepulse.net, gurus.dedyn.io, mememoe.com, portal.intuition.systems,
grokipedia.com.

Samples: `spikes/out/verify_*_raw.json`, `spikes/out/test4_summary.json`.

---

## Test 5 — Monitors lifecycle

**Criterion:** create → run → list runs/changes → delete, with exact request/response shapes.

**Result: PASS.** Full lifecycle worked first try with the minimum config from the docs.

**Exact request body that worked** (`POST /monitors`):
```json
{
  "name": "meme-genealogy spike - lemmy memes",
  "target": { "type": "page", "url": "https://lemmy.world/c/memes?dataType=Post&sort=New" },
  "schedule": { "type": "interval", "frequency": 10, "unit": "minutes" }
}
```
No `webhook` key at all (omitted, not `null`) is a valid "no webhook" config. 10 minutes is the documented
minimum interval (`frequency × unit ≥ 10 minutes`).

**Response shapes (field names actually returned):**
- `POST /monitors` → `mode, id, name, tags, policies, change_detection{type}, schedule{type,frequency,unit},
  webhook, status, last_run_at, last_change_at, next_run_at, last_error, webhook_failure, created_at,
  updated_at, target{type,url}, initial_run_id, key_metadata{credits_consumed, credits_remaining}, request_id`.
  `change_detection` defaulted to `{"type": "exact"}` since none was specified.
- `POST /monitors/{id}/run` → `monitor_id, run_id, queued, key_metadata, request_id` (HTTP 202).
- `GET /monitors/{id}/runs` → `data[]` of
  `{id, monitor_id, status, run_type, target_type, change_detection_type, started_at, completed_at,
  change_detected, change_id, baseline_created, credits_charged, skip_reason, error}`, plus `has_more,
  next_cursor, key_metadata, request_id`.
- `GET /monitors/{id}/changes` → `{data: [], has_more, next_cursor, key_metadata, request_id}` (empty — nothing
  changed on the page between baseline and the on-demand run, as expected over a ~25s window).
- `DELETE /monitors/{id}` → `{id, deleted: true, key_metadata, request_id}` (HTTP 200).
- Confirmed gone: `GET /monitors/{id}` afterward → HTTP 404, `{"message":"Monitor not found","error_code":"NOT_FOUND",...}`.

**Surprise:** the on-demand `run` didn't actually run again — the monitor's baseline run (from `/monitors`
creation) was still in flight, so the run-list shows the triggered run as `status: "skipped"`,
`skip_reason: "superseded"`, `credits_charged: 0`. Only the original baseline run executed
(`run_type: "baseline"`, `credits_charged: 1`). **For a real on-demand re-run you need to wait for the current
run to finish before calling `/run` again** (or accept that an immediate second trigger may be a no-op).

**Surprise 2:** none of the `/monitors/*` endpoints set `X-Credits-Used` in the response headers — credits are
only visible via `key_metadata.credits_consumed` in the JSON body (0 for all calls here except the baseline run,
which charged 1 credit, visible on the run-list entry rather than on the call that queued it).

**Webhook payload field names** (from docs, not tested live — no webhook configured in this spike):
- `run.completed` event: `{ id, data: { run: <run object>, change: <change object or null> } }`, also echoed in
  the `X-Context-Id` header.
- `change.detected` event: `{ id, data: { change: <full change record> } }`.

Samples: `spikes/out/monitor_create_raw.json`, `monitor_run_raw.json`, `monitor_runs_raw.json`,
`monitor_changes_raw.json`, `monitor_delete_raw.json`, `test5_summary.json`.

---

## Other surprises / gotchas worth flagging

- **Credits reporting is inconsistent across endpoint families**: `/web/scrape` and `/web/search` use the
  `X-Credits-Used` response header as the brief expected; `/monitors/*` endpoints never set that header and
  instead report cost via `key_metadata.credits_consumed` in the JSON body. Any production credit-tracking
  code needs to branch on endpoint, not assume the header is always present.
- **HTTP 200 does not mean "got the real page."** old.reddit.com returned 200 with a login wall three times in
  a row; only the first response had an explicit `error_code: WEBSITE_BLOCKED` — the other two looked
  successful by status code alone. Any scrape pipeline needs a content sanity check (e.g. "did I get ≥N posts"),
  not just a status-code check.
- `jsonParams` schema-based extraction seems to work from the page's markdown/text representation, not the raw
  DOM — it missed `<img>` `src`/`alt` attributes that plain `images`/`html` formats captured fine. For
  image-heavy pages, prefer `images`+`html` over `json` schema extraction.
- Our own debug helper (`spikes/common.save_json`, which truncates to 20k chars before writing) occasionally
  wrote invalid/truncated JSON for large raw responses — harmless for this spike (we read the in-memory data
  before truncation) but worth noting as a footgun if this helper is reused: don't truncate JSON files, truncate
  text samples only.
