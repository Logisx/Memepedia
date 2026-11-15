# Memepedia — current status

Last updated: 2026-11-15 (afternoon EET; the Gemma guardrail and the dedupe/stamps/tree work are on `bugfix/final-fixes`, not yet live). Read this first when picking the project up in a new session.

## In one paragraph

Memepedia is a hackathon project (Junction 2026, team of two, main challenge: Context.dev "The Web Is Your Real-Time Database"). It is a live meme genealogy site: posts seen on social feeds minutes ago are stamped with the meme family they belong to, and any meme can be traced back to its origin with a quoted source on every link. Backend and frontend both live on `main` and `pipeline`, which are in sync except for the PR #9 merge commit; `pipeline` is still the branch to work from. The backend code is written end to end and tested: the database layer, every route of the contract (both `GET` and `POST`), the Context.dev client, the three source fetchers, the image lookup, the Gemini client, the name resolver, the trace with quote verification, the live loop with emerging-meme detection, and the curated seed data. PRs #7, #8 and #9 are merged (looser stamping, orphan cleanup, sensitive-tree query param, stricter Rising, frontend polish, Know Your Meme blocklist fix, the overnight collection run, the staging backup, more seed relatives, the architecture slide). Context.dev monitors are live and the overnight run has already happened once; see `claude_docs/plans/2026-11-14_night-run_plan.md` and `claude_docs/plans/2026-11-14_staging-backup_plan.md` for how both were built, and "Still open" below for the morning-of checklist and what is still unfinished (the Imgflip top-100 step, 32 uncited new links, a handful of relative-less memes, the demo script and backup video).

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
| The overnight collection run (monitors + clock fallback, cost guards, webhook security) — design and status | `claude_docs/plans/2026-11-14_night-run_plan.md` |
| The frozen staging copy for demo fallback — design and status | `claude_docs/plans/2026-11-14_staging-backup_plan.md` |
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
| Re-match pending sightings against the archive as it is now, from their saved vision labels (template guess, depicted character, then post title). Dry run unless `--apply`; no Gemini call unless `--llm`, then at most `--max-llm` (default 50). Prints its target database first | `uv run python scripts/rematch.py [--apply] [--hours N] [--llm] [--max-llm 50]` |
| Look again at badly stamped sightings: never-read images (default; `--apply` labels up to `--max`, two calls each), old "not a meme" posts (`--not-memes`), or expired specimens' memes back to pending (`--orphans`, no paid calls). Dry run unless `--apply` | `uv run python scripts/relook.py [--apply] [--max 80] [--not-memes \| --orphans]` |
| Fingerprint every image (no paid calls; runs in both modes) and mark the reposts already in the archive (`--apply`) | `uv run python scripts/dedupe.py [--apply] [--workers 8]` |
| Read-only snapshot of the stamping: states, why images were not read, orphans, shared image URLs, and with `--name` every post mentioning a meme but not stamped with it. Never writes, works before a deploy | `uv run python scripts/diagnose.py [--name "Jensen Huang"]` |
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
- PR #7 (teammate's `bugfix/various-fixes`) merged into `main`: looser stamping (exact-match from confidence 0.7, `VISION_EXACT_MIN_CONFIDENCE`; subject-rule stamping, `VISION_MATCH_SUBJECTS`; see "Decisions made" below), `scripts/rematch.py`, orphan cleanup in `trace.materialise` and `store.delete_nodes`, `/api/tree/{id}?sensitive=true`, stricter Rising ("Decisions made" below), phone layout, a Compare button, the SFW/NSFW toggle label, the Sightings tab following the toggle, and 19 new seed memes. Follow-up fixes on the same PR: generic subject aliases ("The Child", child, chad, big brain) are skipped for subject-rule stamping; `_merge_aliases` unions seed and learned aliases but drops the generic learned ones.
- PR #8 (`pipeline`): the Know Your Meme citation-leak fix described below is merged into `main`.
- PR #9 (this round, four branches): the overnight collection run (`feat/night-run` — Context.dev monitors as the primary clock, the Modal clock as a fallback, cost guards, webhook security; see `claude_docs/plans/2026-11-14_night-run_plan.md`); the frozen staging copy (`feat/staging-backup`; see `claude_docs/plans/2026-11-14_staging-backup_plan.md`); more seed relatives (`data/more-relatives`); frontend polish (`fix/frontend-polish`: bigger SFW/NSFW toggle, Compare stale-pick fix, picker Enter-key race fix, `DescentStrip` left fade on phones, non-stamped wall tiles open the original post); and the architecture slide `claude_docs/demo/architecture.{svg,png}`.
- **Context.dev monitors**: 16 created, one per feed, every 10 minutes, webhook signed to `/api/webhooks/context`. Per-monitor secrets are stored in a DB table (`webhook_monitors`); the first signed delivery was confirmed and an unsigned call was refused with 401. The old "no secret = accept anyone" behaviour is gone. See `claude_docs/plans/2026-11-14_night-run_plan.md`.
- **Cost guards** (`memepedia/budget.py`, DB-backed, rolling 24 h): 3000 Context.dev credits, 5000 Gemini calls, 10 background traces; background work stops 500 short of the Context.dev limit; kill switch `scripts/budget.py off`; `/api/health` reports `paid_work` and `last_webhook_s`.
- **Production deployed with `MEMEPEDIA_CLOCK=1`** (from `main` fd9e216): the clock is now scheduled but acts only as a fallback — it stays idle while signed monitor webhooks keep arriving (20-minute heartbeat, `MEMEPEDIA_CLOCK_FALLBACK_MINUTES`). Deploy from WSL only: build `web/` with `VITE_API_BASE= npm run build` (Linux Node), then from `backend/`: `MEMEPEDIA_CLOCK=1 uv run --with modal modal deploy deploy.py`. Deploying without `MEMEPEDIA_CLOCK=1` unschedules the fallback clock — always include it.
- **Staging backup**: database `memepedia_staging` (same Aiven service) cloned from production and frozen read-only; Modal app `memepedia-staging` deployed with no paid keys, read-only API, no clock, at `https://aleksandr-shishkov-work--memepedia-staging-web.us-east.modal.run`. Health counts matched production at clone time (157 nodes, 191 links, 425 sightings, 97 history); `POST /api/trace` correctly answers 503. Deploy it only with `MEMEPEDIA_APP=memepedia-staging` — any app name other than `memepedia` now deploys a frozen copy, never a second writer on production.
- **The week backfill**: `scripts/backfill.py` run over the Lemmy feeds — 50 posts (11 resolved, 23 pending, 15 unclassified), 0 Context.dev credits spent.
- **Rematch applied** (`scripts/rematch.py --apply`): 28 pending sightings re-stamped against the archive as it stands (4, then a further 24).
- **NSFW re-label progress**: `scripts/label_nsfw.py` labelled 38 previously-unlabelled nodes as safe (they had been blurred under the SFW toggle). 30 sightings remain unlabelled (unreachable or unreadable images) and stay hidden under SFW — see "Still open".
- **More seed relatives** (`data/more-relatives`, production): 25 new nodes and 41 new links giving families to previously lone memes — an AI-slop parent joining Shrimp Jesus and Italian Brainrot, Studio Ghibli, a Herzog-documentary relative for Nihilist Penguin, Predator (1987), UNO, stock photography, Sweating Towel Guy, 67 Kid — plus families for memes the live feed is now naming on its own: Jensen Huang (correction, 2026-11-15: he only got a format link to Reaction image, no relatives; his page now shows his posts as groups instead), SpongeBob/Squidward, Press F, Domino Effect, Is This a Pigeon?, We Are Not the Same, Skeptical Third World Child, Jackie Chan WTF, Peter Parker's Glasses, Obama Awards Obama a Medal. 10 of the 42 new links are cited (286 credits); 32 remain "citation needed" — see "Still open". The learned alias "Sweating Towel Guy" was removed from `two-buttons` (it belongs to its own node now).
- Orphan node `big-bird-in-a-meeting` and the junk node `a-stylized-painting-of-a-wide-eyed-black-cat-...` were deleted from production; `6-7` was marked safe (`nsfw=false`) and given relatives.

## In progress

- **Duplicates, a stamp on every tile, posts in the tree** (2026-11-15, `bugfix/final-fixes`, plan `claude_docs/plans/2026-11-15_dedupe-stamps-tree_plan.md`): built and tested (412 tests), not deployed. Every image is read (Pillow: GIF/AVIF/WebP, Reddit full-size images, Lemmy proxy links unwrapped); unclassified tiles say "one-off" or "not read yet"; reposts are detected by image URL and fingerprint, saved with `duplicate_of` and hidden; a post title naming a meme stamps it (`VISION_MATCH_TITLES`); a meme's page shows up to 48 posts, a character's appearances in other templates included, as groups in its family map. Also on the branch: the NSFW guardrail on Gemma (see "Assumptions made", item 2). The production steps (backup, deploy, `dedupe.py`, `relook.py`, `rematch.py`, `diagnose.py` before and after) are the top section of `claude_docs/TODO_WITH_ENV.md`.
- **Modern memes**: the shortlist the owner approved (Skibidi Toilet, Chill Guy, Moo Deng, Grimace Shake, Nihilist Penguin, Shrimp Jesus, Studio Ghibli AI filter, Bombardiro Crocodilo, Tralalero Tralala, Absolute Cinema, Labubu, 100 Men vs 1 Gorilla) is seeded and mostly has relatives now — see "More seed relatives" above and "Done". Chill Guy, Always Has Been and Left Exit 12 still have no honest relatives (see "Still open"); everything else on the shortlist is covered.

## Not done

- The Imgflip top 100 step of the seed (`--steps templates`, then `verify` for the new links). The curated part of the seed is done, see "State of the data". Verifying a link costs 6 to 7 credits, so 100 templates with one or two links each come to roughly 600 to 1300 credits: check the credit balance with the owner first.
- NSFW re-label is still incomplete: 30 sightings remain unlabelled (see "Done" and "Still open").
- The 3-minute demo script and a backup video are still not written/recorded. The demo script exists only in conversation, not as a file.

## Decisions made

- Know Your Meme is not scraped (its terms forbid aggregation). The client refuses its URLs and search excludes it.
- A node is a meme format; a single post is a sighting attached to a node.
- Two lines of descent per meme: character and format. Every meme ends at a format-class root.
- Links are "cited" (verbatim quote found) or "inferred" (shown dashed as "citation needed").
- Live sources: Lemmy (direct JSON API), Reddit RSS through Context.dev, Imgflip through Context.dev.
- Backend in Python (uv, FastAPI); frontend a static React app. The halves meet only at `contract/`.
- Positioning: an open cultural archive in the spirit of Wikipedia; no advertising.
- A sighting gets a family stamp only when the vision model's guess resolves to a node (an exact name from 0.7 confidence, a near one from 0.85), a depicted character names exactly one node, or (2026-11-15, on `bugfix/final-fixes`) the post title names exactly one meme outright. A meme with no stamp is shown "unidentified"; since 2026-11-15 a post that is not a template shows "one-off" and one whose image could not be read "not read yet", so every wall tile carries a stamp.
- The webhook's signature check only runs when `CONTEXTDEV_WEBHOOK_SECRET` is set; with no secret set it accepts any caller, and each accepted call can trigger a feed fetch that spends credits. The secret must be set before the backend gets a public URL.
- Hosting (owner, 2026-11-14): Modal for the backend and Aiven for Postgres. Both wait on the owner's signups; until then the backend runs on the laptop.
- Seed budget (owner, 2026-11-14): the full seed is affordable. Run it in priority order so the demo is covered first: Wojak, Doge and Pepe, then the other curated families, then the Imgflip top 100.
- Advice Animals on the family map (owner, 2026-11-14): left as it is for now. They show as single nodes; the demo families are unaffected.
- Clock schedule (owner, option 3, 2026-11-14 night; superseded): the Modal clock was switchable via `MEMEPEDIA_CLOCK` and paused. It is now deployed on, but only as a fallback behind the Context.dev monitors — see `claude_docs/plans/2026-11-14_night-run_plan.md` and "Done".
- Context.dev monitors and webhook secret (owner, 2026-11-14 night): approved and created — 16 monitors, one per feed, every 10 minutes; see "Done". The architecture slide's clock box still needs correcting (see "Still open").
- Staging backup (owner, 2026-11-14 night): approved and built as a frozen, read-only copy for a demo fallback — see "Done" and `claude_docs/plans/2026-11-14_staging-backup_plan.md`.
- NSFW policy (owner, 2026-11-14): strict and demo-safe. NSFW sightings are removed from the wall; nodes with an NSFW or unlabelled image are hidden/blurred until a person reveals them by clicking.
- "Rising today" rule (2026-11-14; `store.spike_baseline`): the strip showed memes with only two posts, one post cross-posted to two communities counted twice, and the usual rate was averaged over days the archive had not been collecting. A meme now rises only with at least 3 distinct posts (by title) in 24 hours, at least twice its usual daily rate over the prior days actually observed, and only once the archive has been collecting for 3 days. Until then the strip is empty on purpose; the week backfill (`scripts/backfill.py`, seen_at = post time) is what gives it history sooner. "New specimens" is unchanged: it lists memes the archive added in the last 7 days, which includes old well-known templates the clock traced for the first time.
- SFW/NSFW toggle (owner, 2026-11-14; was labelled "Sensitive"; the label shows the current mode, with the same emoji, and SFW is the default): the header toggle also reveals flagged and unlabelled sightings. `/api/wall` and `/api/tree/{id}` both take `sensitive=true`; the wall refetches when it is flipped, and so does a meme's Sightings tab (only the sightings are replaced). Default off, so the demo stays safe.
- Modern memes shortlist (owner, 2026-11-14): approved — see "In progress".
- Stamping more sightings (owner, 2026-11-14; plan in `claude_docs/plans/2026-11-14_identification-recall_plan.md`): a guess that exactly equals an archive name or alias is stamped from confidence 0.7 (`VISION_EXACT_MIN_CONFIDENCE`); any other guess still needs 0.85 (`VISION_MIN_CONFIDENCE`). A post with no usable guess is stamped by the one *character* node its `subjects` name exactly (no fuzzy match, no LLM; two characters or a template means no stamp; a few generic one-word names such as Walter and Cameraman are skipped). `VISION_MATCH_SUBJECTS=0` turns that off. Code in `live.match_label` and `resolver.Matcher`. Written and tested (276 tests pass on Linux), **not yet deployed**.
- Cloudinary (owner, 2026-11-14): was only an optional idea in the original plan (an image host plus a side challenge); never implemented, and now dropped. Images stay hotlinked from their original sources (nodes mostly `i.imgflip.com`; sightings from Lemmy CDNs and `i.redd.it`).
- Priorities (owner, 2026-11-14): fix only important breaking bugs for now; speed is not a priority (a trace taking a few minutes is acceptable). Next step after the work in progress is for the owner to check the app end to end and prepare the demo.

## Assumptions made while the owner was away (say if any is wrong)

1. **Database.** Docker is not reachable from this WSL and there is no Aiven connection string, so development uses the self-starting local Postgres described above. It has no `pg_trgm`; search uses plain `ILIKE`.
2. **Gemini model.** `gemini-3.8-flash` for everything except the NSFW guardrail (`GEMINI_MODEL` overrides). The cheaper `gemini-3.5-flash-lite` was confidently wrong on 4 of 5 test images. `gemini-2.5-flash-lite` answers 404 on this key.
   **NSFW guardrail model** (owner, 2026-11-15): a separate Gemma call, `gemma-3-27b-it` by default (`GUARDRAIL_MODEL` overrides), decides `nsfw` for every new post, every dropped image and `scripts/label_nsfw.py` (`llm.label_nsfw_only`). Gemini still labels the meme; its own `nsfw` answer is used only when the Gemma call fails or its answer is unreadable, and a Gemini safety block still counts as NSFW without a Gemma call. Gemma has no JSON-schema mode on the Gemini API, so it is asked for JSON in the prompt and parsed leniently. Each Gemma call counts as one Gemini call against the cost cap, so a tick now uses about two calls per post. Not yet checked against the real key: see `TODO_WITH_ENV.md`.
3. **Code standards.** The relaxed set proposed earlier: full typing, Ruff, strict mypy, short functions, tests for pure logic, smoke scripts for anything that calls an external service.
4. **Synchronous code** throughout; parallel work uses thread pools.
5. **Format roots.** Ten instead of the mock data's six (added comparison, exploitable, multi-panel comic, copypasta, catchphrase, video remix), because the real families needed them.

## Decisions waiting on the owner

1. **Hosting — done.** The backend and the built frontend are both live on Modal at `https://aleksandr-shishkov-work--memepedia-web.us-east.modal.run` (also `PUBLIC_BASE_URL` in `.env`): the `web` function stays warm and serves both the API and the built `web/` site. **Warning:** `modal deploy deploy.py` replaces the whole app, so only deploy from an up-to-date `main`/`pipeline`; deploying needs `backend/.env` (repo root) and access to the `aleksandr-shishkov-work` Modal workspace.
2. **Context.dev monitors and webhook secret — done.** 16 monitors created and running, one per feed, every 10 minutes, each with its own signed webhook secret stored in the DB. See "Done" and `claude_docs/plans/2026-11-14_night-run_plan.md`.
3. **Hand-check of seed facts.** Sixteen nodes were flagged `uncertain` in `seed.json`; their dates were confirmed and corrected on 2026-11-14 (commit 51f4757). Sixteen uncertain seed facts are still listed as open below under "Still open" — check `seed.json` directly if this is inconsistent.
4. **Modelling gap (parked).** Advice Animals are related through the format line only, so the character-family map shows each as a single node. The owner chose to leave this for now. If it is picked up later: either the map draws format links, or the strip defaults to the format line for such memes.

## Working agreements

- `main` is protected: no commits, merges or pushes to it without the owner's explicit confirmation. `main` and `pipeline` are in sync except for the PR #9 merge commit; new work should branch from `pipeline`, never from `main`.
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
- Specimen expiry (`store.expire_specimens(days=7)`): deletes a `specimen` node older than 7 days with no sighting in the last 7 days. 19 of the current specimens have no relatives and will be removed by this rule if they stay unvisited (see "Still open").
- The known orphan `big-bird-in-a-meeting` and the junk node `a-stylized-painting-of-a-wide-eyed-black-cat-...` have been deleted from production.
- **Current production counts (after the week backfill and the overnight run, 2026-11-15 just after midnight): 157 nodes, 191 links, 483 sightings (rising as the monitors keep delivering), 97 history rows.** Backups taken along the way: `backend/.data/aiven_before_pr7_seed.json`, `aiven_before_relatives_seed.json`, `aiven_before_night_run.json` (JSON exports, not `pg_dump`, because the bundled `pg_dump` can't negotiate Aiven's required SSL).
- The week backfill has run: 50 Lemmy posts (11 resolved, 23 pending, 15 unclassified), 0 Context.dev credits. Context.dev monitors are live (see "Done"); the Modal clock is deployed as their fallback, not paused.
- Context.dev credits spent in this round: 16 (well under budget); Gemini calls: 60. See `scripts/budget.py status` for the current rolling-24h totals before the demo (morning checklist, "Still open").

## Still open

- Tests need Linux/WSL: the database guard refuses the local test database on Windows (it accepts only a unix-socket server), so `uv run pytest -q` runs there only. 346 tests pass; ruff and `uv run mypy memepedia scripts` are clean; web lint and build pass.
- **Rising today is still empty.** It needs at least 3 days of archive history (see "Decisions made"), and the week backfill gave only a handful of stamped posts, not three days' worth — it will fill in as the monitors keep collecting.
- **32 of the 42 new relative links are "citation needed"** (10 are cited) — see "Done" (more seed relatives).
- **Chill Guy, Always Has Been and Left Exit 12 have no honest relatives yet.**
- **19 auto-detected specimens have no relatives.** They expire automatically (`store.expire_specimens`) after 7 days with no sighting.
- **Monitor secrets are stored unencrypted in the DB** (`webhook_monitors` table) — fine for the hackathon, worth flagging if this goes further.
- **Webhook payload fields were confirmed only by the first signed delivery**; worth re-checking against a few more deliveries before relying on any field not yet seen.
- **Staging shares the production `avnadmin` Aiven credentials** (same service, different database) — see `claude_docs/plans/2026-11-14_staging-backup_plan.md` for why that was judged acceptable.
- **Morning-of checklist** (from the night-run plan): check `scripts/budget.py status`, review what the overnight specimens look like, make sure the kill switch is off before the demo, and decide whether the monitors should keep running during the demo itself.
- **Demo prep**: the backup demo video is not recorded; the 3-minute demo script exists only in conversation, not as a file.
- The Imgflip top-100 templates step of the seed (`--steps templates`, then `verify`) — not run; budget check needed first (roughly 600-1300 credits).
- **NSFW re-label is incomplete**: 30 sightings remain unlabelled (unreachable or unreadable images) and stay hidden under SFW.
- Sixteen older uncertain seed facts plus 11 new ones are flagged `uncertain` in `seed.json` — still not hand-checked against a source.
- Three seed memes missing images (Consoomer, Foul Bachelor Frog, Ridiculously Photogenic Guy).
- `mypy memepedia tests` reports pre-existing errors in 6 test files; `mypy memepedia scripts` is clean.
- **Identification-recall investigation finding**: pending posts that fail to stamp are almost all real memes missing from the archive, not a threshold problem — the stamping thresholds should stay as they are. The real gap is that there is no clustering path for "the same recurring subject across different templates" (the Jensen Huang case is the example that surfaced this).
- **The architecture slide's clock box is stale**: it says "visits one feed every minute"; it should say monitors poll every 10 minutes with the clock as a fallback (see "Done" and the night-run plan).
