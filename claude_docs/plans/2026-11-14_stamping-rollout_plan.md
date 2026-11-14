# Plan: roll the stamping change and the new seed families out to production

For a Claude session running on a machine that has the repo-root `.env`, `uv`, and Modal access.
Written 2026-11-14. Read `claude_docs/STATUS.md` and `claude_docs/plans/2026-11-14_identification-recall_plan.md` first.

## What is being rolled out (already built and committed on `bugfix/various-fixes`)

1. **The stamping change**: exact guesses stamp from confidence 0.7, a depicted character can stamp a
   post with no guess, and `scripts/rematch.py` re-matches old pending posts. `deploy.py` sends the
   three `VISION_*` settings to Modal.
2. **New seed families** in `backend/memepedia/data/seed.json`: 19 new nodes and 39 links that
   production does not have yet (Italian Brainrot, Skibidi Toilet, Grimace, That's Not Cinema, Moo Deng,
   Despicable Me, Baby Yoda, Duckroll, Labubu, plus IQ Bell Curve under Wojak). The seed lists 43 new
   links, but 4 of them copy format links production already has.
3. **Trace orphan fix**: `trace.materialise` deletes the nodes it created when it cannot place a meme
   (`store.delete_nodes`). The orphan it already left, `big-bird-in-a-meeting`, is still in production.
4. **Frontend**: the meme page works on phones; the Compare page has a Compare button; the content
   toggle is labelled SFW / NSFW (SFW by default).
5. **Sightings tab follows the toggle**: `GET /api/tree/{id}` takes `sensitive=true`, and the meme page
   sends it. Backend and frontend must go out together, which one deploy does.
6. **"Rising today" rule** (`store.spike_baseline`): at least 3 distinct posts in 24 hours, twice the
   usual rate, and 3 days of archive history. After the deploy the row is **empty** until that history
   exists; that is expected, not a bug.
7. A README with screenshots (nothing to roll out).

Goal: they are live on production, the new families show on the site, and old pending posts are
re-stamped where that is right.

## Rules

- Anything run from `backend/` with `DATABASE_URL` in `.env` writes to the **hosted production
  database**. Never print or commit anything from `.env`.
- **No commit trailers**: no `Co-Authored-By` or other attribution lines in commit messages. Small commits.
- `main` is protected: no commit, merge or push to it without the owner's explicit OK (see checkpoints).
- Stop at every **CHECKPOINT** below and ask the owner; an earlier OK does not cover a later one.
- Credits: Context.dev budget for this whole rollout is **350 credits**. Read `backend/.data/credits.jsonl`
  before and after each step and stop if the running total would exceed it. Gemini: no step below should
  need more than 50 calls.
- If a step fails, stop and report; do not retry in a loop or work around a guard.

## Checkpoints (owner's explicit go-ahead needed)

| # | Before | Ask |
|---|---|---|
| A | Step 3, seeding production | Show the backup path and the diff of what the seed will add |
| B | Step 4, spending credits on `verify` | State the estimate (6 to 7 credits per link) and the budget |
| C | Step 6, merging into `main` | The PR link and the passing test result |
| D | Step 7, deploying | The commit hash being deployed |
| E | Step 10, `rematch.py --apply` | The saved dry-run list and the spot-check result |

## Steps

### 0. Orient (read-only)

- [ ] Confirm you are on `bugfix/various-fixes` and it contains `fa2bcb2` or later: `git log --oneline -10`.
      The branch may not be on GitHub yet; if `git pull` finds nothing, ask the owner to push it.
- [ ] Confirm the tools: repo-root `.env` exists (do not print it); `uv --version`;
      `uv run --with modal modal profile current` shows the `aleksandr-shishkov-work` workspace;
      `gh auth status` works (needed for the PR).
- [ ] Note the credit ledger total: sum of `credits` in `backend/.data/credits.jsonl` (the file may not
      exist on a fresh machine; then start from 0 and say so).
- [ ] Tests only run on Linux/WSL (the database guard refuses the local test database on Windows). If
      you are on Windows, run them in WSL from an isolated copy and never touch the repo's own
      `.venv` or `.pgdata`: copy `backend` and `contract` to the WSL home (`tar --exclude=.venv
      --exclude=.pgdata --exclude=.git`), then `UV_PROJECT_ENVIRONMENT=$HOME/mp-check-venv uv run pytest -q`.
      `uv` is at `~/.local/bin` in the owner's WSL.

### 1. Stop the seed overwriting learned aliases (small code change)

`scripts/seed.py` `step_families` upserts every seed node with `aliases=raw["aliases"]`, which
**replaces** aliases the resolver learned in production (`store.add_alias`). Re-running it would lose them.

- [ ] Add a pure helper `_merge_aliases(seed: list[str], existing: list[str], name: str) -> list[str]`:
      seed aliases first, then any existing alias not already there; case-insensitive de-duplication;
      drop any alias equal to the node's name. Use it in `step_families`
      (`aliases=_merge_aliases(raw["aliases"], existing.aliases if existing else [], raw["name"])`).
- [ ] Add `tests/test_seed.py` with unit tests for the helper only (new seed alias, an existing learned
      alias kept, duplicates differing in case, alias equal to the name). Do **not** call `step_families` in
      a test: it would load the whole seed into the shared test database.
- [ ] `uv run ruff check .`, `uv run ruff format --check memepedia scripts tests`,
      `uv run mypy memepedia scripts`; tests in WSL as above. Commit.

### 2. Back up production (read-only on the database)

- [ ] `pg_dump` ships inside the backend's environment (`backend/.venv/Lib/site-packages/pgserver/pginstall/bin/pg_dump.exe`
      on Windows, `.../lib/python3.12/site-packages/pgserver/pginstall/bin/pg_dump` on Linux):
      `pg_dump -Fc "$DATABASE_URL" -f backend/.data/before_rollout_<date>.dump`.
      Otherwise export JSON with a short `uv run python -` snippet that reads `nodes`, `links`, `sightings`
      (all columns including `vision`) and `history` through `memepedia.db.fetch_all` and writes
      `backend/.data/before_rollout_<date>.json` (use `json.dump(..., default=str)`). Both paths are git-ignored.
- [ ] Check the file is non-empty and report the row counts per table.

### 3. Seed the new families  — CHECKPOINT A

- [ ] Show the owner the backup path and what will be added: the 19 new node ids and 39 new links are
      the ones in `seed.json` that production does not have (compare against `GET /api/nodes?limit=1000`).
      Wait for the go-ahead.
- [ ] `uv run python scripts/seed.py --steps families` (does not need credits). Expect the counts line and
      `credits spent this run: 0.0`.
- [ ] `uv run python scripts/seed.py --steps images`. It looks up an image for each node without one;
      credits may be spent (record them). Some AI-character nodes may find no image.
- [ ] Read-only check against production: for each head in `italian-brainrot, skibidi-toilet, grimace,
      not-cinema, moo-deng, despicable-me, baby-yoda, duckroll, labubu` fetch
      `<PUBLIC_BASE_URL>/api/tree/<id>` and assert `family_ids` has at least 2 entries; assert
      `iq-bell-curve`'s tree includes `wojak` in `family_ids`; assert `rickroll`'s
      `descent.character` is `["rickroll", "duckroll", "reaction-image"]`. List the new nodes with no
      `image_url` for the owner.

- [ ] Ask the owner about the orphan `big-bird-in-a-meeting` (no links, image or date; the code bug that
      made it is fixed in this branch). If they agree, delete it with `store.delete_nodes(["big-bird-in-a-meeting"])`
      (a one-off `uv run python -` snippet) and say so in the report. Its sightings, if any, become unclassified.
- [ ] Ask the owner about Wojak: it is flagged `nsfw = true` in production, so it is blurred everywhere
      (including the README screenshot). If they say its image is fine:
      `uv run python scripts/set_nsfw.py node wojak false`.
- [ ] Note for the owner: the families step also promotes `sad-baby-yoda` and `iq-bell-curve` from
      `specimen` to `established` (on purpose: specimens start expiring on 2026-11-21).

### 4. Cite the new links (optional, costs credits)  — CHECKPOINT B

- [ ] Ask the owner whether to spend credits (about 6 to 7 per link, roughly 230 to 270 for all 39; the
      demo families alone, Italian Brainrot, Skibidi Toilet and Despicable Me, are roughly 100).
- [ ] If yes, **always narrow with `--families`**; without it `verify` re-checks every inferred link in
      the archive, including ones that already failed:
      `uv run python scripts/seed.py --steps verify --families italian-brainrot,skibidi-toilet,despicable-me`,
      then `grimace,not-cinema,moo-deng,baby-yoda,duckroll,labubu` only if the budget allows.
- [ ] Record "checked / cited" and the credits spent. Links that find no quote stay "inferred" (dashed),
      which is fine.

### 5. Open the PR

- [ ] `git push -u origin bugfix/various-fixes`; `gh pr create --base main --head bugfix/various-fixes`
      with a short description of the changes listed at the top of this plan, the test result (276
      passed), the new `VISION_*` settings, and that "Rising today" will be empty until there are 3 days of
      history. Do not add attribution lines to the description unless the owner asks.

### 6. Merge into `main`  — CHECKPOINT C

- [ ] Send the owner the PR link and test result. **Wait for their OK**; the owner may merge it
      themselves. Do not merge on your own.
- [ ] After the merge: `git checkout main && git pull`; confirm `git log -1` is the merge commit and
      `git status` is clean. **Deploy only from an up-to-date `main`**, because `modal deploy` replaces the
      whole app.

### 7. Deploy  — CHECKPOINT D

- [ ] Tell the owner the commit hash about to be deployed; wait for the go-ahead.
- [ ] `.env` may hold the optional settings `VISION_EXACT_MIN_CONFIDENCE` (default 0.7),
      `VISION_MIN_CONFIDENCE` (0.85) and `VISION_MATCH_SUBJECTS` (1); `deploy.py` now sends them to Modal.
      Leave them unset unless the owner says otherwise. Leave `MEMEPEDIA_CLOCK` as it is (the clock is
      paused; do not turn it on).
- [ ] Windows: `.\backend\deploy.ps1`. Linux/WSL: from `web/` run `npm ci` then `VITE_API_BASE= npm run
      build`, then from `backend/` run `uv run --with modal modal deploy deploy.py`.
- [ ] Verify (read-only):
      - `GET <PUBLIC_BASE_URL>/api/health` returns 200; `/api/wall` and `/api/nodes` respond; the home page loads.
      - `/api/tree/tung-tung-tung-sahur` returns `family_ids` with 7 entries.
      - `/api/tree/doomer?sensitive=true` returns 200 (the old code ignored the parameter; the new code
        includes flagged sightings).
      - `/api/week` answers; an empty `rising` list is expected (see change 6 at the top).
      - The site at phone width (390 px): the meme page stacks with no sideways scrolling, and the
        Compare page has a Compare button. The header button reads "🙈 SFW" in a fresh browser.
- [ ] If the deploy fails or the site is broken: redeploy the previous `main` commit
      (`git checkout <previous merge commit>` then the same deploy command) and report. Do not touch the database.

### 8. Measure (read-only)

- [ ] Run these two queries through `memepedia.db.fetch_all` and give the owner the results.

      Where posts drop out:
      ```sql
      SELECT CASE
               WHEN vision IS NULL THEN '1 no image / download failed'
               WHEN NOT (vision->>'is_meme')::boolean THEN '2 not a meme'
               WHEN vision->>'template_guess' IS NULL THEN '3 no guess'
               WHEN (vision->>'confidence')::float < 0.85 THEN '4 low confidence'
               ELSE '5 guess not in archive'
             END AS reason, count(*)
      FROM sightings WHERE state <> 'resolved' GROUP BY 1 ORDER BY 1;
      ```
      Recurring subjects among pending posts:
      ```sql
      SELECT s AS subject, count(*) FROM sightings, jsonb_array_elements_text(vision->'subjects') s
      WHERE state = 'pending' GROUP BY 1 ORDER BY 2 DESC LIMIT 60;
      ```

### 9. Add the recurring topic memes (only if the owner wants it)

- [ ] From the subjects query, propose to the owner up to 10 real, recurring topics worth a character node
      (for example Jensen Huang for the Nvidia memes). Wait for their choice.
- [ ] For each chosen one, add a `kind: "character"` node to `seed.json` plus one format link, following the
      existing entries. Verify the facts (dates, who or what it is) with a web search; mark `uncertain: true`
      with a `check_note` when a date is not confirmed. Check a parent is not younger than its child.
- [ ] Commit, repeat steps 1's checks, then step 3's two seed commands (backup first again, checkpoint A
      applies), and merge and deploy only if the owner wants it live now. The re-match in step 10 can
      use the new nodes straight away, since it reads the database.

### 10. Re-match the old pending posts  — CHECKPOINT E

- [ ] Dry run (no Gemini calls, changes nothing), saved so it can be undone:
      `uv run python scripts/rematch.py | tee backend/.data/rematch_<date>.txt`.
      It prints the target database first; confirm it is production.
- [ ] Spot-check 20 proposals, covering every `subject` one first: look up each sighting's `post_url`,
      `title` and `image_url` by id, download the image into the scratchpad, view it, and judge whether
      the stamped node is right. Report the table (id, node, via, right or wrong).
- [ ] Decide with the owner: if more than 2 of the 20 are wrong, run `rematch.py` with
      `VISION_MATCH_SUBJECTS=0` in the environment for that run (and consider setting it in `.env` and
      redeploying); if exact or near matches are wrong, say so rather than applying.
- [ ] Only with the owner's OK: `uv run python scripts/rematch.py --apply | tee
      backend/.data/rematch_<date>_applied.txt`. Report `stamped: N`.
- [ ] Optional, spends Gemini calls (at most 50): the same dry run with `--llm --max-llm 50` first, then with `--apply`.
- [ ] Undo, if asked: only the sightings listed in the saved file, only those: `UPDATE sightings SET state
      = 'pending', node_id = NULL WHERE id = ANY(%s)` with that id list.

### 11. Report

Give the owner a short summary: nodes and links added; images found and missing; credits spent against
the 350 budget; the deployed commit; the two measurement results; how many sightings were re-stamped by
`exact`, `near` and `subject`; anything skipped or failing; and a list of things still open from `claude_docs/TODO_WITH_ENV.md` (overnight clock,
Context.dev monitors, week backfill, Imgflip top 100). Update `claude_docs/STATUS.md` with what is now
live and commit it.

## Rollback summary

- Code: redeploy the previous `main` commit.
- Seed: the backup from step 2; or delete only the new node ids (links cascade).
- Re-match: the saved list from step 10.
- Stamping rules: set `VISION_MATCH_SUBJECTS=0` or raise `VISION_EXACT_MIN_CONFIDENCE` in `.env`, then redeploy.
