# Memepedia — current status

Last updated: 2026-11-14 18:10 EET. Read this first when picking the project up in a new session.

## In one paragraph

Memepedia is a hackathon project (Junction 2026, team of two, main challenge: Context.dev "The Web Is Your Real-Time Database"). It is a live meme genealogy site: posts seen on social feeds minutes ago are stamped with the meme family they belong to, and any meme can be traced back to its origin with a quoted source on every link. The owner gave the go-ahead on 2026-11-14 and the backend is being built on the `pipeline` branch. The backend code is written end to end and tested: the database layer, every route of the contract (both `GET` and `POST`), the Context.dev client, the three source fetchers, the image lookup, the Gemini client, the name resolver, the trace with quote verification, the live loop with emerging-meme detection, and the curated seed data. All of it is committed and pushed to `origin/pipeline`. What remains is running it for real (the full seed, the week backfill, the live loop), deployment, monitors, and the merge with the frontend.

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
| Deploy the API and the website to Modal (one URL; the API was live and tested 2026-11-14, the site is new on branch `feature/hosting` and not yet deployed) | `.\backend\deploy.ps1` builds `web/` with an empty `VITE_API_BASE`, then runs `modal deploy`. Set `$env:MEMEPEDIA_APP = "memepedia-staging"` first for a throwaway copy (no warm container, no clock); remove it with `modal app stop memepedia-staging` |

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
- Tests for the four `POST` routes (`backend/tests/test_api_post.py`). The whole suite is 187 tests, all passing; Ruff and strict mypy are clean.
- Deployed to Modal (2026-11-14 ~17:15 EET): `backend/deploy.py`'s `web` function (kept warm) and `clock` function (every minute, one feed per tick) are both live at `https://aleksandr-shishkov-work--memepedia-web.us-east.modal.run`. All routes respond 200; CORS and the `/api/trace` SSE stream (events arrive incrementally, not buffered) both check out. The clock has already resolved several sightings into the wall.

## In progress

Nothing is half-written right now. The backend code is complete for the planned build; what is left is running it for real (below) and deployment.

## Not done

- The Imgflip top 100 step of the seed (`--steps templates`, then `verify` for the new links). The curated part of the seed is done, see "State of the data". Verifying a link costs 6 to 7 credits, so 100 templates with one or two links each come to roughly 600 to 1300 credits: check the credit balance with the owner first.
- The week backfill: `scripts/backfill.py` has not been run.
- Context.dev monitors are not set up yet; the one-minute Modal clock is the live loop's source of ticks for now (see "Decisions waiting on the owner").
- The merge with the frontend.

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

## Assumptions made while the owner was away (say if any is wrong)

1. **Database.** Docker is not reachable from this WSL and there is no Aiven connection string, so development uses the self-starting local Postgres described above. It has no `pg_trgm`; search uses plain `ILIKE`.
2. **Gemini model.** `gemini-3.8-flash` for everything (`GEMINI_MODEL` overrides). The cheaper `gemini-3.5-flash-lite` was confidently wrong on 4 of 5 test images. `gemini-2.5-flash-lite` answers 404 on this key.
3. **Code standards.** The relaxed set proposed earlier: full typing, Ruff, strict mypy, short functions, tests for pure logic, smoke scripts for anything that calls an external service.
4. **Synchronous code** throughout; parallel work uses thread pools.
5. **Format roots.** Ten instead of the mock data's six (added comparison, exploitable, multi-panel comic, copypasta, catchphrase, video remix), because the real families needed them.

## Decisions waiting on the owner

1. **Hosting (done 2026-11-14 ~17:15 EET).** The backend is live on Modal: `https://aleksandr-shishkov-work--memepedia-web.us-east.modal.run` is the public base URL (now also `PUBLIC_BASE_URL` in `.env`). The `web` function stays warm and serves the API; the `clock` function runs every minute, visiting one feed per tick in rotation, and is already producing sightings (first run ~17:16, 99 sightings by 17:25). `CONTEXTDEV_WEBHOOK_SECRET` is still unset, so the webhook accepts any caller for now — set it before turning on Context.dev monitors (see below).
2. **Context.dev monitors, not yet turned on.** `scripts/monitors.py create --dry-run` (run against the live `PUBLIC_BASE_URL`) shows it would create 16 monitors, one per feed, each polling every 10 minutes and pointing its webhook at `<PUBLIC_BASE_URL>/api/webhooks/context`. Two things needed first: the `whsec_...` webhook signing secret (not found in this repo — `spikes/P0_RESULTS.md` Test 5 created a monitor with no `webhook` key at all, so no secret was ever returned; per `contextdev.py`'s docstring it is either returned when a monitor/webhook is created with one, or copied from the Context.dev dashboard — needs checking there), and a credit-budget decision: `spikes/P0_RESULTS.md` Test 5 shows a monitor's baseline run costs 1 credit (`credits_charged: 1`); an immediately-following on-demand run was skipped as "superseded" at 0 credits, so the real per-run cost in steady state (one run per 10-minute interval, 16 monitors) still wants the owner's go-ahead.
3. **When `pipeline` goes into `main`.** The code is pushed on `pipeline` (`origin/pipeline` is level with the local branch); `main` is untouched and equals `origin/main`. Open question: merge `pipeline` into `main` now so the teammate can branch `web` from `main`, or have them branch `web` from `pipeline` directly and merge everything into `main` later. Needs the owner's say.
4. **Hand-check of seed facts.** Sixteen nodes are flagged `uncertain` in `seed.json` with a note on what to check: crying-wojak, brainlet, coomer, yes-chad, grug, doge, swole-doge-vs-cheems, walter, sad-frog, smug-frog, sadge, chad, average-fan-vs-average-enjoyer, paranoid-parrot, success-kid, drake-hotline-bling. The three demo families (Wojak, Doge, Pepe) matter most.
5. **Modelling gap (parked).** Advice Animals are related through the format line only, so the character-family map shows each as a single node. The owner chose to leave this for now. If it is picked up later: either the map draws format links, or the strip defaults to the format line for such memes.

## Working agreements

- `main` is protected: no commits, merges or pushes to it without the owner's explicit confirmation. Work happens on `pipeline` (backend) and `web` (frontend).
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
- 2026-11-14 ~17:25 EET: an agent ran `load_fixtures.py --reset` expecting `MEMEPEDIA_DB` to point it at a local database. With `DATABASE_URL` set in `.env`, every script targets the hosted Aiven database and `MEMEPEDIA_DB` is ignored, so the hosted tables were dropped and mock data served for about 20 minutes. It was restored from a 17:24 export (see "State of the data"). Since commit 615b285, `db.reset_schema()` and `load_fixtures.py` refuse to run unless the database is the local dev server (a unix socket in `backend/.pgdata`); there is no override.

## State of the data

- `contract/fixtures/` is mock data: 31 nodes, illustrative dates and quotes, some source URLs on Know Your Meme. It is for the frontend to build against and is not loaded into the real archive.
- `backend/memepedia/data/seed.json` is the real seed. Its dates and relations come from the model's own knowledge and have not been checked against a source by a person (for example Wojak 2009, Pepe 2005, Doge 2010); each is stored with a precision of year, month or day. Every link starts as "inferred"; the seed script's verify step turns it "cited" when it finds a quote.
- The local database (`memepedia`) holds the real curated seed since 2026-11-14 16:45: 72 nodes and 70 links, no sightings yet. Images were found automatically for 59 of 62 memes (none for Consoomer, Foul Bachelor Frog, Ridiculously Photogenic Guy); nobody has looked at them.
- Link verification of the curated seed: 41 of 70 links are "cited". By family: Wojak 17 of 23, Doge 4 of 9, Pepe 11 of 13, everything else 9 of 25. Advice Animals did worst: most of their format links found no quote.
- Quality of the citations is uneven. 16 of the 41 come from meme.com and several from small aggregator sites; only a handful come from Wikipedia, Daily Dot, Dictionary.com or MEL. Some quotes carry footnote digits glued to the text ("September 20183"). Neither has been fixed.
- A backup of this verified archive is in `backend/.data/archive_curated_verified.dump` (git-ignored, `pg_dump -Fc`). Do not run `seed.py --reset` without it: the citations cost about 510 credits to produce.
- The hosted Aiven database was wiped at ~17:25 and restored at 17:45 EET from `backend/.data/after_templates_trial.json` (17:24 export: 85 nodes, 81 links of which 41 cited, 89 sightings, 52 history). Lost: the clock's sightings and any auto-traced rows between 17:24 and 17:45. Afterwards the orphan node `i-am-once-again-asking-for-your-financial-support` (no links, sightings or history) was deleted, and the monkas -> pepe-the-frog quote had its leading footnote links removed (the clean sentence was checked on the page). At 18:09 the hosted database held 96 nodes, 93 links (44 cited), 316 sightings, 67 history; the clock keeps adding to it.
- Snapshots in `backend/.data/` (git-ignored): `aiven_before_templates.json` (17:18), `after_templates_trial.json` (17:24, the restore source), `step2_consolidated_repairs.json` (the quote repairs), `aiven_wiped_state.json` (the mock data that was served, kept as a record), `aiven_restored.json` (18:09, after the restore and the two fixes).
- The week backfill has not been run. On the laptop the live loop is not running; the Modal clock is.
- Context.dev credits: the backend ledger `backend/.data/credits.jsonl` shows 598 credits since 15:59 on 2026-11-14 (585 on quote verification, 13 on Reddit and Imgflip fetches), on top of roughly 55 from the feasibility tests. About 85 of those were wasted by re-checking 13 demo-family links that had already failed once.
