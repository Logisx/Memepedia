# Memepedia — current status

Last updated: 2026-11-14 evening EET. Read this first when picking the project up in a new session.

## In one paragraph

Memepedia is a hackathon project (Junction 2026, team of two, main challenge: Context.dev "The Web Is Your Real-Time Database"). It is a live meme genealogy site: posts seen on social feeds minutes ago are stamped with the meme family they belong to, and any meme can be traced back to its origin with a quoted source on every link. Backend and frontend are both merged into `main`: `pipeline` (the owner's backend) was merged into `main` with the owner's explicit OK, and the teammate's `web` branch (the frontend, in `web/`) had already been merged into `main` earlier via PR #1. `pipeline` has since been fast-forwarded to `main`, so both branches now carry backend and frontend together. The backend code is written end to end and tested: the database layer, every route of the contract (both `GET` and `POST`), the Context.dev client, the three source fetchers, the image lookup, the Gemini client, the name resolver, the trace with quote verification, the live loop with emerging-meme detection, and the curated seed data. The two bugs found when the frontend first exercised the deployed backend (see `claude_docs/MERGE_TRYOUTS.md`) — trace and proposals — are fixed. The NSFW guardrail and hosting are merged and deployed (see "Done"). What remains: Context.dev monitors, the week backfill, the Imgflip top-100 step, the NSFW re-label, and the in-progress modern-memes additions below.

## Where everything is

| What | Where |
|---|---|
| Product, logic, demo script, positioning | `claude_docs/plans/2026-11-14_meme-genealogy_plan.md` |
| Build order for the backend half (the repo owner) | `claude_docs/plans/2026-11-14_backend-pipeline_plan.md` |
| Build order for the frontend half (the teammate) | `claude_docs/plans/2026-11-14_frontend-experience_plan.md` |
| JSON shapes both halves agree on | `contract/types.ts`, `contract/README.md` |
| Mock data, one file per endpoint | `contract/fixtures/` (see its README; run `python3 -I contract/fixtures/check_fixtures.py` to validate) |
| Feasibility test scripts, samples and results | `spikes/`, results in `spikes/P0_RESULTS.md` |
| Backend code | `backend/memepedia/` (package), `backend/scripts/`, `backend/tests/` |
| Frontend code | `web/` (static React app) |
| Frontend teammate's try-out report against the deployed backend (two failures, trace and proposals — both now fixed) | `claude_docs/MERGE_TRYOUTS.md` |
| Curated seed data (roots and five families) | `backend/memepedia/data/seed.json` |
| Secrets | `.env` (git-ignored): `CONTEXTDOTDEV_KEY`, `GEMINI_KEY`, `GEMINI_EMAIL`, `GEMINI_PASSWORD` |
| Context.dev credit ledger (local, git-ignored) | `backend/.data/credits.jsonl` |

## Running the backend

All commands from `backend/`, with uv.

| To do this | Run |
|---|---|
| Tests, lint, types | `uv run pytest -q`, `uv run ruff check .`, `uv run mypy memepedia scripts` |
| Fill the local dev database with the mock archive (refused on any other database) | `uv run python scripts/load_fixtures.py [--reset]` |
| Start the API on port 8000 | `uv run uvicorn memepedia.api:app --port 8000` |
| Check the sources, image lookup, Gemini live | `uv run python scripts/smoke_sources.py [--platform lemmy\|reddit\|imgflip]`, `smoke_images.py`, `smoke_llm.py` |
| Live-check one trace, printing each event | `uv run python scripts/smoke_trace.py --query "Doomer" [--context "..."] [--specimen]` |
| Live-check one tick on one feed | `uv run python scripts/smoke_live.py --feed <key>` |
| Build the real archive: curated families, Imgflip templates, images, link verification | `uv run python scripts/seed.py [--reset] [--steps families,templates,images,verify] [--limit N] [--workers N] [--families wojak,doge]` (`--families` narrows the verify step to those families, in that order) |
| Backfill a week of Lemmy history as sightings | `uv run python scripts/backfill.py [--max-images 120]` |
| Run the laptop clock (visits feeds in rotation until there is a public URL) | `uv run python scripts/run_loop.py [--every 45] [--once] [--platform lemmy\|reddit\|imgflip]` |
| Manage Context.dev page monitors (one per feed) | `uv run python scripts/monitors.py create\|list\|delete [--dry-run]` |
| Deploy the API and the website to Modal (one URL; both are live in production as of 2026-11-14 at `https://aleksandr-shishkov-work--memepedia-web.us-east.modal.run`) | `.\backend\deploy.ps1` builds `web/` with an empty `VITE_API_BASE`, then runs `modal deploy`. On Linux/WSL (no `deploy.ps1`): from `web/`, `VITE_API_BASE= npm run build`, then from `backend/`, `uv run --with modal modal deploy deploy.py`. `.env` lives at the repo root. Prefix `MEMEPEDIA_APP=memepedia-staging` first for a throwaway copy (no warm container, no clock); remove it with `modal app stop memepedia-staging`. `modal deploy` replaces the whole app, so deploy only from an up-to-date `main` |

The database is a local PostgreSQL 16 that starts itself on first use (the `pgserver` package, data in `backend/.pgdata/`). Setting `DATABASE_URL` in `.env` switches to a hosted Postgres with no code change. `MEMEPEDIA_DB` picks the local database name (default `memepedia`; tests use `memepedia_test`), and is ignored whenever `DATABASE_URL` is set. The frontend points at the backend with `VITE_API_BASE=http://localhost:8000`.

## Done

- Research, the two-round plan review, the split into two halves with a contract and mock data.
- Context.dev feasibility tests (about 55 credits): Reddit works through RSS, Imgflip through the `images` and `html` formats, quote verification found a sentence for 4 of 5 links, monitors work at a 10-minute interval.
- Vision go/no-go test: **go**. Gemini named 5 of 5 established templates correctly with one borderline name; only 2 of 20 Lemmy posts used a template already in the archive. Details in `spikes/P0_RESULTS.md`, Test 6.
- Backend step B1: schema (nodes, links, sightings, history), query layer, graph logic (lines of descent, common ancestor, cycle and date checks), all `GET` routes, fixtures loader, contract tests.
- Context.dev client with a credit ledger; fetchers for 9 Lemmy communities, 5 subreddits and 2 Imgflip streams; image lookup (Imgflip template search, then Wikipedia).
- Gemini client: vision label, lineage draft, same-or-new check, quote pick, clustering of pending sightings. One call each, structured output, one retry.
- Name resolver: exact match first, the model only for near matches, aliases remembered.
- Curated seed: 10 format-class roots, 62 memes, 70 links (Wojak 20, Advice Animals 17, Pepe 12, Doge 7, Chad 4, plus Distracted Boyfriend and Drake).
- The trace: hypothesises a meme's lineage with an LLM, verifies it against the live web, and serves proposals.
- The quote verifier: finds a sentence on the open web that supports one lineage link, verbatim, and turns network or model failures into a clean "no evidence" instead of a crash.
- The seed script: builds the real archive from curated families, Imgflip templates, images and link verification, in one run or by step.
- The live loop: one tick fetches fresh posts from one feed, labels them, resolves them to a family, and saves sightings; `tick_all` runs every feed plus emerging-meme detection and specimen expiry.
- Emerging-meme detection: clusters pending unclassified sightings and turns a qualifying cluster into a new specimen.
- Image identification: names the meme in an uploaded image, or says what to trace instead.
- The clock scripts: `run_loop.py` (a local rotation until there is a public URL) and `monitors.py` (Context.dev page monitors as the clock once there is one).
- The four `POST` routes, wired in `backend/memepedia/api.py`: `/api/trace` (a server-sent event stream), `/api/identify` (image upload, 5 MB limit), `/api/proposals`, `/api/webhooks/context`. The first three share a per-minute call budget (trace 12, identify 20, proposals 12) that answers 429 once spent, so a looping client cannot drain paid quotas. The webhook answers quickly and runs the feed tick in the background, ignores repeated deliveries of the same event id, and checks the `X-Context-Signature` header only when `CONTEXTDEV_WEBHOOK_SECRET` is set.
- Tests for the four `POST` routes (`backend/tests/test_api_post.py`). The suite is now 210 tests, all passing; Ruff is clean. Strict mypy (`uv run mypy memepedia scripts`) is clean; `mypy memepedia tests` still reports pre-existing errors in 6 test files (see "Still open").
- Deployed to Modal (2026-11-14 ~17:15 EET, redeployed since with the fixes below): `backend/deploy.py`'s `web` function (kept warm) and `clock` function are both live at `https://aleksandr-shishkov-work--memepedia-web.us-east.modal.run`. All routes respond 200; CORS and the `/api/trace` SSE stream (events arrive incrementally, not buffered) both check out.
- The Modal clock's schedule is now switchable by the `MEMEPEDIA_CLOCK` env var (unset = paused, `MEMEPEDIA_CLOCK=1` turns it on; set it in `backend/.env` or the shell and redeploy). **It is currently paused** — it does not run every minute any more; see "Decisions made" and "Still open".
- Auto-trace fix: a pending sighting only triggers an automatic trace once the same template guess has been seen from at least 2 distinct authors inside the 72-hour pending window, and the result is created as a `specimen` node (not `established`).
- Proposals scrape fix: the Context.dev `formats` argument was being sent as `{"markdown": {}}` (an object), which Context.dev rejected with 400 ("Could not read that page"); it is now sent as booleans.
- Gemini reliability fix: per-attempt timeout raised from 20 s to 60 s with one retry; the `/api/trace` SSE stream emits a "Still thinking…" `StatusEvent` every 8 s while waiting, and a timeout now produces a specific error message instead of a generic failure.
- Live verification after redeploy, same URL: proposals works end to end (tried against the Wikipedia Wojak page, correctly and honestly rejected with "no citable sentence" in about 4 s); trace on "Rickroll" completed in about 116 s (roughly 60 s for Gemini's first draft, roughly 52 s for a citation search that found none, so the link to video-remix was inferred). The owner has accepted that trace latency of a few minutes is fine for the demo; speed is not a current priority.
- **NSFW guardrail** (PR #3) and **hosting** (PR #4, the built web app served by the backend on the same Modal URL) both merged into `main` (f7508aa) and deployed to production at `https://aleksandr-shishkov-work--memepedia-web.us-east.modal.run`. Smoke-tested 2026-11-14: `/`, deep links (`/meme/doomer`, `/trace`) return the site, `/api/health` ok (113 nodes, 110 links, 425 sightings), an unknown `/api/*` path returns a JSON 404, the wall returns only `nsfw=false` sightings. The clock is still paused (`MEMEPEDIA_CLOCK` unset).
- NSFW: the first strict backfill flagged 14 nodes (mostly the Pepe/Wojak family: angry-pepe, brainlet, coomer, feels-good-man, gigachad, good-guy-greg, monkas, pepe-the-frog, pepehands, pink-wojak, rare-pepe, sad-frog, virgin-vs-chad, wojak), 85 sightings, with 31 unlabelled (hidden); flagged nodes show blurred in the archive and their sightings are off the wall. Manual override: `uv run python scripts/set_nsfw.py <node|sighting> <id> <true|false>`; backfill: `scripts/label_nsfw.py`.
- NSFW guardrail and hosting (PR #3 and PR #4) merged into `main` (f7508aa) and deployed to production — see below.

## In progress

- **Modern memes**: adding a shortlist the owner approved — Skibidi Toilet, Chill Guy, Moo Deng, Grimace Shake, Nihilist Penguin, Shrimp Jesus, Studio Ghibli AI filter, Bombardiro Crocodilo, Tralalero Tralala, Absolute Cinema, optionally Labubu and 100 Men vs 1 Gorilla. Candidates tracked in `backend/.data/modern_memes_candidates.json`.

## Not done

- The Imgflip top 100 step of the seed (`--steps templates`, then `verify` for the new links). The curated part of the seed is done, see "State of the data". Verifying a link costs 6 to 7 credits, so 100 templates with one or two links each come to roughly 600 to 1300 credits: check the credit balance with the owner first.
- The week backfill: `scripts/backfill.py` has not been run.
- Context.dev monitors are not set up yet; the webhook signing secret has not been created either (the owner asked for an explanation of what it is before proceeding) — see "Still open".
- NSFW re-label: the prompt was revised to judge the image, not the character's reputation (`llm._NSFW_POLICY`), but production labels are still from the first strict backfill — see "Still open" and §10 of `claude_docs/plans/2026-11-14_backend-pipeline_plan.md`.
- Known orphan node `big-bird-in-a-meeting` (no link to anything) — an orphan bug in `trace.materialise` / `_attach_rootless`, not yet fixed. The owner says individual-meme bugs like this are low priority for now.
- The 3-minute demo script and a backup video are still not written/recorded.

## Decisions made

- Know Your Meme is not scraped (its terms forbid aggregation). The client refuses its URLs and search excludes it.
- A node is a meme format; a single post is a sighting attached to a node.
- Two lines of descent per meme: character and format. Every meme ends at a format-class root.
- Links are "cited" (verbatim quote found) or "inferred" (shown dashed as "citation needed").
- Live sources: Lemmy (direct JSON API), Reddit RSS through Context.dev, Imgflip through Context.dev.
- Backend in Python (uv, FastAPI); frontend a static React app. The halves meet only at `contract/`.
- Positioning: an open cultural archive in the spirit of Wikipedia; no advertising.
- A sighting gets a family stamp only when the vision model is at least 0.85 confident and the name resolves to a node. Anything else is shown unstamped.
- The webhook's signature check only runs when `CONTEXTDEV_WEBHOOK_SECRET` is set; with no secret set it accepts any caller, and each accepted call can trigger a feed fetch that spends credits. The secret must be set before the backend gets a public URL.
- Hosting (owner, 2026-11-14): Modal for the backend and Aiven for Postgres. Both wait on the owner's signups; until then the backend runs on the laptop.
- Seed budget (owner, 2026-11-14): the full seed is affordable. Run it in priority order so the demo is covered first: Wojak, Doge and Pepe, then the other curated families, then the Imgflip top 100.
- Advice Animals on the family map (owner, 2026-11-14): left as it is for now. They show as single nodes; the demo families are unaffected.
- Clock schedule (owner, option 3, 2026-11-14): the Modal clock is switchable via `MEMEPEDIA_CLOCK` and is currently paused rather than running every minute; turn it on deliberately when wanted.
- NSFW policy (owner, 2026-11-14): strict and demo-safe. NSFW sightings are removed from the wall; nodes with an NSFW or unlabelled image are hidden/blurred until a person reveals them by clicking.
- Modern memes shortlist (owner, 2026-11-14): approved — see "In progress".
- Cloudinary (owner, 2026-11-14): was only an optional idea in the original plan (an image host plus a side challenge); never implemented, and now dropped. Images stay hotlinked from their original sources (nodes mostly `i.imgflip.com`; sightings from Lemmy CDNs and `i.redd.it`).
- Priorities (owner, 2026-11-14): fix only important breaking bugs for now; speed is not a priority (a trace taking a few minutes is acceptable). Next step after the work in progress is for the owner to check the app end to end and prepare the demo.

## Assumptions made while the owner was away (say if any is wrong)

1. **Database.** Docker is not reachable from this WSL and there is no Aiven connection string, so development uses the self-starting local Postgres described above. It has no `pg_trgm`; search uses plain `ILIKE`.
2. **Gemini model.** `gemini-3.8-flash` for everything (`GEMINI_MODEL` overrides). The cheaper `gemini-3.5-flash-lite` was confidently wrong on 4 of 5 test images. `gemini-2.5-flash-lite` answers 404 on this key.
3. **Code standards.** The relaxed set proposed earlier: full typing, Ruff, strict mypy, short functions, tests for pure logic, smoke scripts for anything that calls an external service.
4. **Synchronous code** throughout; parallel work uses thread pools.
5. **Format roots.** Ten instead of the mock data's six (added comparison, exploitable, multi-panel comic, copypasta, catchphrase, video remix), because the real families needed them.

## Decisions waiting on the owner

1. **Hosting — done.** The backend and the built frontend are both live on Modal at `https://aleksandr-shishkov-work--memepedia-web.us-east.modal.run` (also `PUBLIC_BASE_URL` in `.env`): the `web` function stays warm and serves both the API and the built `web/` site. **Warning:** `modal deploy deploy.py` replaces the whole app, so only deploy from an up-to-date `main`/`pipeline`; deploying needs `backend/.env` (repo root) and access to the `aleksandr-shishkov-work` Modal workspace.
2. **Context.dev monitors and webhook secret — not created.** The owner asked for an explanation of what the webhook signing secret is and does before proceeding, so this is still open rather than merely waiting on a budget call. `scripts/monitors.py create --dry-run` (run against the live `PUBLIC_BASE_URL`) shows it would create 16 monitors, one per feed, each polling every 10 minutes and pointing its webhook at `<PUBLIC_BASE_URL>/api/webhooks/context`. Needed: the `whsec_...` webhook signing secret (per `contextdev.py`'s docstring, returned when a monitor/webhook is created with one, or copied from the Context.dev dashboard), and a credit-budget decision (a monitor's baseline run costs about 1 credit; steady-state cost for 16 monitors polling every 10 minutes still wants a go-ahead).
3. **Hand-check of seed facts.** Sixteen nodes were flagged `uncertain` in `seed.json`; their dates were confirmed and corrected on 2026-11-14 (commit 51f4757). Sixteen uncertain seed facts are still listed as open below under "Still open" — check `seed.json` directly if this is inconsistent.
4. **Modelling gap (parked).** Advice Animals are related through the format line only, so the character-family map shows each as a single node. The owner chose to leave this for now. If it is picked up later: either the map draws format links, or the strip defaults to the format line for such memes.

## Working agreements

- `main` is protected: no commits, merges or pushes to it without the owner's explicit confirmation. `pipeline` and `web` have both been merged into `main`, and PR #3 (NSFW guardrail) and PR #4 (hosting) have since merged into `main` too; new work should branch from an up-to-date `main`/`pipeline`.
- Commit regularly, with small commits.
- The main session decides; subagents do the legwork: Opus for outsourced thinking, Sonnet for implementation, Haiku for cheap fact-gathering (verify what Haiku returns).
- Never print or commit anything from `.env`.
- Stay modest with Gemini usage (at most 10 images per live tick) and track Context.dev credits.

## Things learned the hard way

- A blocked page can return HTTP 200. Check content, not status.
- Context.dev's JSON-schema extraction reads the page as text and misses image attributes; use the `images` and `html` formats when the data lives in tags.
- A Context.dev monitor run requested while the first baseline run is in flight is skipped.
- Monitor endpoints report credits in the response body, not in the `X-Credits-Used` header.
- Full-page JSON extraction on a large page can take 45 seconds; keep it out of request paths.
- Format links are harder to find citations for than character links.
- Image sourcing needs its own lookup step: Imgflip's template search first, then Wikipedia's page thumbnail.
- Check a subagent's verdict against the raw output. The vision test was first reported as a failure on all three thresholds; the hand labels were off by one and the model had been right.
- A command piped into `tail` hides a failing exit code. Do not chain a commit after a piped test run.
- On Lemmy, most posts are one-off jokes with no template. Expect many unstamped tiles from that source.
- Imgflip stream posts have no timestamp and join to a template name for only 4 or 5 posts per fetch.
- The knowyourmeme.com/kym-cdn.com blocklist checked only each source's URL, never its title or the picked quote text, so a Reddit repost of a Know Your Meme page's own title (e.g. a `r/KnowYourMeme` thread) sailed through every URL check and got stored as a citation.
- 2026-11-14 ~17:25 EET: an agent ran `load_fixtures.py --reset` expecting `MEMEPEDIA_DB` to point it at a local database. With `DATABASE_URL` set in `.env`, every script targets the hosted Aiven database and `MEMEPEDIA_DB` is ignored, so the hosted tables were dropped and mock data served for about 20 minutes. It was restored from a 17:24 export (see "State of the data"). Since commit 615b285, `db.reset_schema()` and `load_fixtures.py` refuse to run unless the database is the local dev server (a unix socket in `backend/.pgdata`); there is no override.

## State of the data

- `contract/fixtures/` is mock data: 31 nodes, illustrative dates and quotes, some source URLs on Know Your Meme. It is for the frontend to build against and is not loaded into the real archive.
- `backend/memepedia/data/seed.json` is the real seed. Its dates and relations come from the model's own knowledge and have not been checked against a source by a person (for example Wojak 2009, Pepe 2005, Doge 2010); each is stored with a precision of year, month or day. Every link starts as "inferred"; the seed script's verify step turns it "cited" when it finds a quote.
- The local database (`memepedia`) holds the real curated seed since 2026-11-14 16:45: 72 nodes and 70 links, no sightings yet. Images were found automatically for 59 of 62 memes (none for Consoomer, Foul Bachelor Frog, Ridiculously Photogenic Guy); nobody has looked at them.
- Link verification of the curated seed: 41 of 70 links are "cited". By family: Wojak 17 of 23, Doge 4 of 9, Pepe 11 of 13, everything else 9 of 25. Advice Animals did worst: most of their format links found no quote.
- Quality of the citations is uneven. 16 of the 41 come from meme.com and several from small aggregator sites; only a handful come from Wikipedia, Daily Dot, Dictionary.com or MEL. Some quotes carry footnote digits glued to the text ("September 20183"). Neither has been fixed.
- 2026-11-14: a production link (`awkward-look-monkey-puppet` -> `reaction-image`, format axis) and its `cited` history row (id 70) carried a Reddit URL (`r/KnowYourMeme`) that laundered a Know Your Meme page title and quote; both were withdrawn (link reset to `inferred`, history row deleted) after exporting them to `backend/.data/kym_rows_before_fix.json` (git-ignored).
- A backup of this verified archive is in `backend/.data/archive_curated_verified.dump` (git-ignored, `pg_dump -Fc`). Do not run `seed.py --reset` without it: the citations cost about 510 credits to produce.
- The hosted Aiven database was wiped at ~17:25 and restored at 17:45 EET from `backend/.data/after_templates_trial.json` (17:24 export: 85 nodes, 81 links of which 41 cited, 89 sightings, 52 history). Lost: the clock's sightings and any auto-traced rows between 17:24 and 17:45. Afterwards the orphan node `i-am-once-again-asking-for-your-financial-support` (no links, sightings or history) was deleted, and the monkas -> pepe-the-frog quote had its leading footnote links removed (the clean sentence was checked on the page). At 18:09 the hosted database held 96 nodes, 93 links (44 cited), 316 sightings, 67 history; the clock keeps adding to it.
- Snapshots in `backend/.data/` (git-ignored): `aiven_before_templates.json` (17:18), `after_templates_trial.json` (17:24, the restore source), `step2_consolidated_repairs.json` (the quote repairs), `aiven_wiped_state.json` (the mock data that was served, kept as a record), `aiven_restored.json` (18:09, after the restore and the two fixes).
- Further data cleanup on the production (Aiven) database, done after the above: an export `backend/.data/aiven_before_option3.json` was taken first; the junk nodes `piaget-s-conservation-of-volume` and `for-the-better-right` were deleted; 23 clock-made nodes were demoted to `specimen`. Counts after cleanup are roughly 103 nodes (80 `established`, including the new `rickroll`, plus 23 `specimen`).
- Specimen expiry (`store.expire_specimens(days=7)`): deletes a `specimen` node older than 7 days with no sighting in the last 7 days. The earliest any of the current specimens can be removed by this is 2026-11-21.
- Known orphan: `big-bird-in-a-meeting` has no link to anything (an orphan bug in `trace.materialise`/`_attach_rootless`, not yet fixed; low priority per the owner).
- The week backfill has not been run. On the laptop the live loop is not running; the Modal clock is paused (see "Decisions made").
- Context.dev credits: the backend ledger `backend/.data/credits.jsonl` shows 598 credits since 15:59 on 2026-11-14 (585 on quote verification, 13 on Reddit and Imgflip fetches), on top of roughly 55 from the feasibility tests. About 85 of those were wasted by re-checking 13 demo-family links that had already failed once.

## Still open

- Context.dev monitors and the webhook signing secret (not created; owner asked for an explanation first — see "Decisions waiting on the owner").
- The week backfill (`scripts/backfill.py` not run).
- The Imgflip top-100 templates step of the seed.
- Sixteen uncertain seed facts (see "Decisions waiting on the owner" #3 for which commit touched these).
- Three seed memes missing images (Consoomer, Foul Bachelor Frog, Ridiculously Photogenic Guy).
- `mypy memepedia tests` reports pre-existing errors in 6 test files; `mypy memepedia scripts` is clean.
- Five tests in `backend/tests/test_trace.py` (the `materialise_*` and trace event-order/heartbeat tests) call real Gemini via the resolver → `llm.same_or_new` when a key is present in `.env`, and fail without one — they should be mocked.
- NSFW re-label: the prompt now judges the image rather than the character's reputation, but production labels still come from the first strict backfill (14 nodes, 85 sightings flagged, 31 unlabelled) — deferred, see §10 of `claude_docs/plans/2026-11-14_backend-pipeline_plan.md`.
- `pipeline` has docs/seed commits not yet on `main` (STATUS updates, the 10 modern memes in `seed.json` — their data is already in production).
- The code fix for the Know Your Meme citation leak (below) is committed on `pipeline` and is not live until it is merged into `main` and deployed with the owner's OK.
