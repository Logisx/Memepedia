# Memepedia — current status

Last updated: 2026-11-14, about 16:25 EET. Read this first when picking the project up in a new session.

## In one paragraph

Memepedia is a hackathon project (Junction 2026, team of two, main challenge: Context.dev "The Web Is Your Real-Time Database"). It is a live meme genealogy site: posts seen on social feeds minutes ago are stamped with the meme family they belong to, and any meme can be traced back to its origin with a quoted source on every link. The owner gave the go-ahead on 2026-11-14 and the backend is being built on the `pipeline` branch. **Committed and tested:** the database layer, every `GET` route of the contract, the Context.dev client, the three source fetchers, the image lookup, the Gemini client, the name resolver, the curated seed data and the vision go/no-go test. **Being built right now (uncommitted, in the working tree):** the trace with quote verification, proposals and the seed script; the live loop, emerging-meme detection, image identification and the clock scripts. **Not started:** wiring the four `POST` routes, the full seed and backfill runs, deployment. Nothing has been pushed to GitHub.

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
| Fill the database with the mock archive | `uv run python scripts/load_fixtures.py --reset` |
| Start the API on port 8000 | `uv run uvicorn memepedia.api:app --port 8000` |
| Check the sources, image lookup, Gemini live | `uv run python scripts/smoke_sources.py`, `smoke_images.py`, `smoke_llm.py` |

The database is a local PostgreSQL 16 that starts itself on first use (the `pgserver` package, data in `backend/.pgdata/`). Setting `DATABASE_URL` in `.env` switches to a hosted Postgres with no code change. `MEMEPEDIA_DB` picks the local database name (default `memepedia`; tests use `memepedia_test`). The frontend points at the backend with `VITE_API_BASE=http://localhost:8000`.

## Done

- Research, the two-round plan review, the split into two halves with a contract and mock data.
- Context.dev feasibility tests (about 55 credits): Reddit works through RSS, Imgflip through the `images` and `html` formats, quote verification found a sentence for 4 of 5 links, monitors work at a 10-minute interval.
- Vision go/no-go test: **go**. Gemini named 5 of 5 established templates correctly with one borderline name; only 2 of 20 Lemmy posts used a template already in the archive. Details in `spikes/P0_RESULTS.md`, Test 6.
- Backend step B1: schema (nodes, links, sightings, history), query layer, graph logic (lines of descent, common ancestor, cycle and date checks), all `GET` routes, fixtures loader, contract tests.
- Context.dev client with a credit ledger; fetchers for 9 Lemmy communities, 5 subreddits and 2 Imgflip streams; image lookup (Imgflip template search, then Wikipedia).
- Gemini client: vision label, lineage draft, same-or-new check, quote pick, clustering of pending sightings. One call each, structured output, one retry.
- Name resolver: exact match first, the model only for near matches, aliases remembered.
- Curated seed: 10 format-class roots, 62 memes, 70 links (Wojak 20, Advice Animals 17, Pepe 12, Doge 7, Chad 4, plus Distracted Boyfriend and Drake).

## In progress

- Trace, quote verifier, proposals, seed script (backend plan step B2 and part of B4).
- Live loop, emerging-meme detection, identify, local clock, week backfill, monitor script (B3 and part of B4).
- A Modal deployment file exists (`backend/deploy.py`) but has never been run: there is no Modal account yet.

## Not done

- The four `POST` routes (`/api/trace`, `/api/identify`, `/api/proposals`, `/api/webhooks/context`).
- The full seed (Imgflip top 100 and verification of every link, roughly 900 credits) and the week backfill.
- Deployment, monitors as the clock (both need a public URL), the merge with the frontend.

## Decisions made

- Know Your Meme is not scraped (its terms forbid aggregation). The client refuses its URLs and search excludes it.
- A node is a meme format; a single post is a sighting attached to a node.
- Two lines of descent per meme: character and format. Every meme ends at a format-class root.
- Links are "cited" (verbatim quote found) or "inferred" (shown dashed as "citation needed").
- Live sources: Lemmy (direct JSON API), Reddit RSS through Context.dev, Imgflip through Context.dev.
- Backend in Python (uv, FastAPI); frontend a static React app. The halves meet only at `contract/`.
- Positioning: an open cultural archive in the spirit of Wikipedia; no advertising.
- A sighting gets a family stamp only when the vision model is at least 0.85 confident and the name resolves to a node. Anything else is shown unstamped.

## Assumptions made while the owner was away (say if any is wrong)

1. **Database.** Docker is not reachable from this WSL and there is no Aiven connection string, so development uses the self-starting local Postgres described above. It has no `pg_trgm`; search uses plain `ILIKE`.
2. **Gemini model.** `gemini-3.8-flash` for everything (`GEMINI_MODEL` overrides). The cheaper `gemini-3.5-flash-lite` was confidently wrong on 4 of 5 test images. `gemini-2.5-flash-lite` answers 404 on this key.
3. **Code standards.** The relaxed set proposed earlier: full typing, Ruff, strict mypy, short functions, tests for pure logic, smoke scripts for anything that calls an external service.
4. **Synchronous code** throughout; parallel work uses thread pools.
5. **Format roots.** Ten instead of the mock data's six (added comparison, exploitable, multi-panel comic, copypasta, catchphrase, video remix), because the real families needed them.

## Decisions waiting on the owner

1. **Hosting and database.** Proposed: Modal for the backend and Aiven free Postgres. Each needs a signup: `modal token new` on this machine, and the Aiven connection string in `.env` as `DATABASE_URL`. Until then the backend runs on the laptop and a local script is the clock. Context.dev monitors need a public URL for their webhook.
2. **How the teammate gets the code.** Nothing has been pushed. Either push `pipeline` and have the teammate branch `web` from it, or merge `pipeline` into `main` first. Both need the owner's say.
3. **Hand-check of seed facts.** Sixteen nodes are flagged `uncertain` in `seed.json` with a note on what to check: crying-wojak, brainlet, coomer, yes-chad, grug, doge, swole-doge-vs-cheems, walter, sad-frog, smug-frog, sadge, chad, average-fan-vs-average-enjoyer, paranoid-parrot, success-kid, drake-hotline-bling. The three demo families (Wojak, Doge, Pepe) matter most.
4. **Modelling gap to raise with the teammate.** Advice Animals are related through the format line only, so the character-family map shows each as a single node. Either the map draws format links, or the strip defaults to the format line for such memes.

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

## State of the data

- `contract/fixtures/` is mock data: 31 nodes, illustrative dates and quotes, some source URLs on Know Your Meme. It is for the frontend to build against and is not loaded into the real archive.
- `backend/memepedia/data/seed.json` is the real seed. Its dates and relations come from the model's own knowledge and have not been checked against a source by a person (for example Wojak 2009, Pepe 2005, Doge 2010); each is stored with a precision of year, month or day. Every link starts as "inferred"; the seed script's verify step turns it "cited" when it finds a quote.
