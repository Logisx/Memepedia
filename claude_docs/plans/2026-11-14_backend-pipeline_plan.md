# Backend plan — the "data and agents" half

Owner: the AI and backend teammate. Branch: `pipeline`. Folders: `backend/`, `spikes/`.

You need nothing from the frontend to finish this plan. The backend is done when its HTTP API returns real data in the shapes of `contract/types.ts`; that is checked by tests, not by a UI.

## 1. What this half delivers

A public HTTP API, a database that fills itself, and two background behaviours:

- **The live loop**: every few minutes, fetch fresh posts from social sources, have a vision model name the template in each image, attach each post to a meme as a sighting, and notice when several unknown posts are the same new thing.
- **The trace**: given a name or an image, draft the meme's line of descent with an LLM, then check every link against the live web and keep a verbatim quote as evidence.

The logic is specified in section 3 of the main plan (`2026-11-14_meme-genealogy_plan.md`). This document is the build order.

## 2. Stack

| Piece | Choice | Why |
|---|---|---|
| Language | Python, managed with uv | Your home ground; nothing to install on this machine (Node is not installed here) |
| API | FastAPI, Pydantic models mirroring `contract/types.ts` | Typed responses; server-sent events for the trace |
| Database | Postgres on Aiven, plain SQL through `psycopg` | Sponsor side challenge; four tables do not need an ORM |
| Web data | Context.dev over `httpx` | Scrape, search, monitors |
| Models | Gemini Flash through `google-genai` | Vision and text with one key; sponsor side challenge |
| Hosting | Modal | Python-native, gives a public URL, scheduled functions and parallel fan-out; sponsor side challenge |

Hosting is the one open choice; see section 7.

## 3. Layout

```
backend/
  pyproject.toml
  memepedia/
    models.py        Pydantic models, one per type in contract/types.ts
    db.py            connection, schema.sql loader, small query helpers
    schema.sql       nodes, links, sightings, history
    contextdev.py    scrape, search, monitor calls
    llm.py           Gemini calls: vision label, draft chain, resolve, cluster
    resolver.py      name or vision label -> existing node, or "new"
    trace.py         hypothesise, verify, invariants, write nodes and links
    sources/         one fetcher per social source, all returning the same Post shape
    live.py          one tick: fetch, look, resolve, save, cluster
    api.py           FastAPI routes in contract order
    deploy.py        Modal app: web endpoint, webhook, schedule
  scripts/
    seed.py          format roots, hand-checked families, Imgflip top 100
    backfill.py      a week of Lemmy posts
    load_fixtures.py load contract/fixtures into the database
  tests/
```

## 4. Steps

Hours are a guide. Commit at each checkpoint.

| Step | Hours | Work | Checkpoint |
|---|---|---|---|
| B0 | 0 to 1.5 | Go/no-go tests (section 5). Get the Gemini API key. Create Aiven Postgres and a Modal account. | Results written to `spikes/P0_RESULTS.md`; sources and fallbacks decided |
| B1 | 1.5 to 3 | Project skeleton. Pydantic models. Schema. All `GET` routes reading from the database. `load_fixtures.py` fills the database with the mock archive. Deploy. | Every `GET` endpoint returns contract-shaped data at a public URL; contract test passes |
| B2 | 3 to 7 | Context.dev and Gemini clients. Resolver with aliases. Trace: draft chain, verify links in parallel, invariants. `POST /api/trace` as an event stream. Seed script; hand-check three demo families. | Tracing "Doomer" from an empty database produces a chain to a root with at least one cited link; seed loaded |
| B3 | 7 to 11 | Source fetchers. Vision labelling. One live tick end to end. Monitor and webhook as the clock. Lemmy week backfill. `/api/wall`, `/api/week`, `/api/identify` on real data. | A post made minutes ago appears in `/api/wall` stamped with a family, without manual action |
| B4 | 11 to 14 | Emerging-meme clustering. `/api/related` (common ancestor per axis). `/api/proposals` with the quote verifier. Latin names. | An unknown trio of posts becomes a specimen; a pasted URL flips a link to cited |
| Merge | 14 to 16 | Hand the public URL to the frontend. Fix contract mismatches. Serve or link the built frontend. | Real data on every screen |
| Wrap-up | 16 to 19 | Freeze. Hand-check demo families. Backup video. Side-challenge notes. | |

If time runs short, cut from the bottom of B4 upward: proposals, then related, then clustering. B2 and B3 are the demo.

## 5. B0 go/no-go tests

| Test | Pass | If it fails |
|---|---|---|
| Vision labelling on 20 hand-labelled Lemmy posts | At least 70% of posts that use a seeded template named correctly; at most 2 confident wrong names; at least 6 of 20 resolve to a node | Stamp families only on high-confidence matches; drop clustering |
| Reddit through Context.dev scrape, three fetches | Each returns at least 20 posts with timestamps and image URLs | Drop Reddit; optionally give Exa 15 minutes |
| Imgflip hot and latest through Context.dev scrape | Posts with image, link and template name | Use only its template list |
| Verify step on 5 known links | A verbatim supporting sentence for at least 3 | Loosen to "a page about the child mentions the parent" |
| Monitor create, run, read changes | Works; payload shape recorded | Scheduled function on the host as the clock |

The vision test needs the Gemini key and is still to do.

### Results of the Context.dev tests (run 2026-11-14, about 55 credits)

Full numbers, request bodies and samples: `spikes/P0_RESULTS.md` and `spikes/out/`.

| Test | Result | What it means for the build |
|---|---|---|
| Reddit | `old.reddit.com` and the `.json` endpoint are blocked (a login wall that sometimes still returns HTTP 200). `reddit.com/r/<sub>/new/.rss` through Context.dev scrape works: 2.5 s, 1 credit, 25 of 25 posts with title, timestamp, author and image. | Reddit is a live source. Build the fetcher on the RSS form. Detect blocks by content, not by status code. |
| Imgflip | JSON-schema extraction misses images because it reads the page as text. `formats: {images: true, html: true}` returns image URLs and alt text for 1 credit. No timestamps; alt text is a tag list, not a clean template name; `?sort=hot` redirects to `/m/fun`. | Usable as a second image source with "seen at" as the time. The vision model still has to name the template. |
| X trends (trends24.in) | Clean extraction of 24 time buckets, 5 credits, but 46 s and mixed countries. | Background job only, never in a request path. Low priority. |
| Verify step | Supporting sentence found for 4 of 5 links. One `/web/search` call with `markdownOptions.enabled` returns page content inline: 3 to 21 s, 4 to 6 credits per link. The miss was a format link (Swole Doge vs. Cheems, Virgin vs. Chad). | The trace design holds. Run link checks in parallel. Expect format links to stay "inferred" more often than character links. |
| Monitors | Create, run, read changes and delete all work with a minimal page-monitor body at a 10-minute interval. A run triggered while the first baseline run is in flight is skipped. Credits appear in the response body, not the header. | Monitors can be the clock. Wait for the baseline run before the first on-demand run. |

Sources for the live loop, in build order: Lemmy (direct JSON), Reddit RSS through Context.dev, Imgflip through Context.dev. That meets the threshold of two image sources with timestamps, one of them through Context.dev.

## 6. How independence is kept

- `load_fixtures.py` gives the API realistic data on day one, before any pipeline exists.
- A contract test calls every endpoint and validates the response against the Pydantic models, and checks that every fixture file validates against the same models. If the fixtures and the models disagree, the contract is ambiguous and gets fixed in `contract/`.
- The trace and the live loop are tested through their own entry points (`trace("doomer")`, `tick("lemmy")`), with recorded Context.dev and Gemini responses for the unit tests and live calls for a small smoke script.

## 7. Decisions needed from you

1. **Gemini API key.** `.env` currently holds the temporary account's email and password. Log in at aistudio.google.com with them, open aistudio.google.com/api-keys, copy the key and add it to `.env` as `GEMINI_API_KEY`. Google's guide warns the account is closed if the key is pushed to GitHub; `.env` is already ignored by git.
2. **Hosting.** Recommended: Modal for the backend. It needs a free account and `modal token new` on this machine. Alternative: run the backend on this laptop behind a tunnel for the hackathon, which is quicker to start but dies if the laptop sleeps.
3. **Database.** Recommended: Aiven free Postgres (sign up, create the service, put the connection string in `.env` as `DATABASE_URL`).
4. **Code standards for the weekend.** Your global rules ask for strict mypy, tests first and functions under 20 lines. Proposed for this project: keep typing, Ruff and short functions; write tests for the pure logic (resolver, invariants, common ancestor, clustering rules, contract shapes) and smoke scripts for anything that calls an external service. Say if you want the full rules applied.
5. **Sharing with your partner.** `pipeline` is pushed to GitHub (`origin/pipeline`). Open question: merge `pipeline` into `main` and have your partner branch from `main`, or have them branch `web` from `pipeline` directly and merge everything into `main` later.

## 8. Credit and quota budget

- Context.dev: 50,000 credits. Expected: tests under 400; seed about 1,500 (three calls per link); live loop about 10 per tick; traces about 20 each. Well under 10,000 in total.
- Gemini: the temporary account is high-quota, but Google disqualifies teams for abuse. Cap vision at 10 images per tick and deduplicate by post URL.

## 9. Risks specific to this half

| Risk | Response |
|---|---|
| Drafted lineage is wrong for a well-known meme | Hand-check the three demo families; invariants; inferred links are shown as such |
| Duplicate nodes from name variants | Every write path goes through the resolver |
| Vision stamps the wrong family | Confidence threshold; unclassified is better than wrong |
| Verification is slow | Verify links in parallel; stream the dashed chain first so the wait is visible progress |
| A source blocks or changes | Every fetcher returns the same `Post` shape; losing one source does not touch the rest |
