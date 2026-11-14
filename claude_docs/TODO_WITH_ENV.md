# To do: things only someone with the repo-root `.env` can do

Last checked against the branch on 2026-11-14 (up to commit `fa2bcb2`). A Claude session can do all of
this by following `claude_docs/plans/2026-11-14_stamping-rollout_plan.md`. Anything run from `backend/`
with a `.env` holding `DATABASE_URL` hits the **hosted production database**. Do the steps in order.

## What is on `bugfix/various-fixes` and not yet live

| Change | Needs |
|---|---|
| 19 new memes and 39 new links in `seed.json` (Italian Brainrot, Skibidi Toilet, Grimace, That's Not Cinema, Moo Deng, Despicable Me, Baby Yoda, Duckroll, Labubu; IQ Bell Curve joins Wojak) | the seed run in step 1 |
| Stamping: exact guesses stamp from 0.7, a depicted character can stamp a post, `scripts/rematch.py` | deploy (step 2), then step 3 |
| Trace no longer leaves orphan memes behind | deploy; the existing orphan `big-bird-in-a-meeting` needs deleting by hand (step 1) |
| `deploy.py` sends `VISION_MIN_CONFIDENCE`, `VISION_EXACT_MIN_CONFIDENCE`, `VISION_MATCH_SUBJECTS` to Modal | deploy |
| Meme page works on phones; Compare page has a Compare button | deploy |
| A meme's Sightings tab follows the toggle (`/api/tree/{id}?sensitive=true`) | deploy (backend and frontend together) |
| The toggle is labelled SFW / NSFW (SFW by default) | deploy |
| "Rising today" needs real evidence (3 distinct posts, twice the usual rate, 3 days of history) | deploy; it will show **nothing** until the archive has 3 days of history (see "Still open") |
| README and screenshots | nothing |

The branch is **not pushed yet** (`git push -u origin bugfix/various-fixes`).

Needs on that machine: `uv`, `.env` at the repo root, Modal access to the `aleksandr-shishkov-work`
workspace, `gh` or the GitHub site for the PR. Tests run on Linux/WSL only (the database guard refuses
the local test database on Windows).

## 0. Before touching anything

- [ ] Back up production. `pg_dump` ships inside the backend's environment
      (`backend/.venv/Lib/site-packages/pgserver/pginstall/bin/pg_dump.exe` on Windows,
      `.../lib/python3.12/site-packages/pgserver/pginstall/bin/pg_dump` on Linux):
      `pg_dump -Fc "$DATABASE_URL" -f backend/.data/before_rollout_<date>.dump` (git-ignored).
      **Why:** the seed's `families` step overwrites every seed meme's name, **aliases**, kind, dates
      and summary with the values in `seed.json` (105 memes). Aliases the resolver learned since the last
      seed would be lost. Step 1 of the rollout plan fixes the seed so it keeps them; do that first, or at
      least copy them out (`SELECT id, aliases FROM nodes`).
- [ ] Note the Context.dev credit balance (dashboard) and the `backend/.data/credits.jsonl` total.
- [ ] `git pull` on `bugfix/various-fixes`; from `backend/` run `uv run pytest -q`, `uv run ruff check .`,
      `uv run mypy memepedia scripts`. Expect all 276 tests to pass on Linux/WSL.

## 1. Put the new families in the archive

- [ ] `uv run python scripts/seed.py --steps families`: adds 19 memes and 39 links (new links start as
      "inferred", shown dashed). It also promotes Sad Baby Yoda and IQ Bell Curve from `specimen` to
      `established` on purpose (specimens with no recent sightings start being deleted on 2026-11-21).
- [ ] `uv run python scripts/seed.py --steps images`: finds an image for every meme that has none. Expect
      a few misses among the AI-character memes.
- [ ] Open the site and look at each new family: Italian Brainrot, Skibidi Toilet, Grimace, That's Not
      Cinema, Moo Deng, Despicable Me, Baby Yoda, Duckroll, Labubu, and Wojak (IQ Bell Curve). Check
      each has an image, a sensible family map, and no "No relatives on record" message. Set images by
      hand for any that are missing.
- [ ] Optional, costs credits (about 6 to 7 per link, roughly 230 to 270 for all 39): turn links into
      cited ones. **Always narrow it with `--families`.** Without it `verify` re-checks every inferred
      link in the archive, including ones that already failed (about 85 credits were wasted that way
      before). Demo families first:
      `uv run python scripts/seed.py --steps verify --families italian-brainrot,skibidi-toilet,despicable-me`
      then the others (`grimace,not-cinema,moo-deng,baby-yoda,duckroll,labubu`).
- [ ] Hand-check the six `uncertain` dates on the new memes (Skibidi Cameraman, TV Man and "Skibidi",
      Tung Tung Tung Sahur, Ballerina Cappuccina, Minion Memes); their `check_note` says what is unconfirmed.
- [ ] Delete the orphan `big-bird-in-a-meeting` (no links, image or date) if you agree: a one-off
      `uv run python -c "from memepedia import store; print(store.delete_nodes(['big-bird-in-a-meeting']))"`
      from `backend/` (needs the branch's code). Its sightings, if any, become unclassified.
- [ ] Optional: Wojak is flagged NSFW in production (`nsfw = true`), so the most famous meme on the site
      is blurred, including in the README screenshot. If its image is fine:
      `uv run python scripts/set_nsfw.py node wojak false`.

## 2. Get the code live

`main` is protected. Merge only with the owner's explicit OK.

- [ ] Push the branch, open a PR from `bugfix/various-fixes` into `main`, and get it merged (owner's OK).
- [ ] `git checkout main && git pull`. Deploy **only from an up-to-date `main`**, because `modal deploy`
      replaces the whole app.
- [ ] Optional settings in `.env` before deploying (defaults shown; `deploy.py` now sends them to Modal):
      `VISION_EXACT_MIN_CONFIDENCE=0.7`, `VISION_MIN_CONFIDENCE=0.85`, `VISION_MATCH_SUBJECTS=1`.
      Leave `MEMEPEDIA_CLOCK` as it is unless you have decided on the overnight clock (see "Still open").
- [ ] Optional dry run first: `$env:MEMEPEDIA_APP = "memepedia-staging"` then `.\backend\deploy.ps1`.
      The staging copy uses the same `DATABASE_URL`, so it reads and writes **production data**; it is a
      code copy, not a data backup. Remove it with `modal app stop memepedia-staging`.
- [ ] Deploy. Windows: `.\backend\deploy.ps1`. Linux/WSL: from `web/` run `npm ci` then
      `VITE_API_BASE= npm run build`, then from `backend/` run `uv run --with modal modal deploy deploy.py`.
- [ ] Check after deploying:
      - `<PUBLIC_BASE_URL>/api/health` answers 200.
      - `/meme/tung-tung-tung-sahur` shows a family of seven.
      - On a phone: the meme page stacks and nothing runs off the right edge; the Compare page has a
        Compare button that stays disabled until two different memes are picked.
      - The header button reads **🙈 SFW** in a fresh browser and **👀 NSFW** after a click.
      - With NSFW on, a meme that has flagged sightings shows them in its Sightings tab.
      - "Rising today" is empty. That is expected until the archive has 3 days of history.

## 3. Measure, then re-match old posts

- [ ] Run the two queries from `claude_docs/plans/2026-11-14_identification-recall_plan.md` ("After it
      lands"): where posts drop out, and which subjects recur among pending posts.
- [ ] Add the recurring real subjects (Jensen Huang for the Nvidia memes, and so on) to `seed.json` as
      `kind: "character"` memes with a format link, check their facts, then step 1 again
      (`--steps families,images`).
- [ ] Dry run: `uv run python scripts/rematch.py` (no Gemini calls, changes nothing). It prints the target
      database first; confirm it is the one you mean. Save the output (`| tee backend/.data/rematch_<date>.txt`)
      so the change can be undone.
- [ ] Read the list, open about 20 of the posts, and check the matches are right. Look hardest at the
      `subject` ones.
- [ ] `uv run python scripts/rematch.py --apply`.
- [ ] Optional, spends Gemini calls: add `--llm --max-llm 50` (dry run first, then with `--apply`).
- [ ] If stamping looks wrong afterwards: raise `VISION_EXACT_MIN_CONFIDENCE`, or set
      `VISION_MATCH_SUBJECTS=0`, and redeploy.

## Still open (not part of this branch)

- [ ] **Overnight clock.** The Modal clock is paused (`MEMEPEDIA_CLOCK` unset) and no Context.dev
      monitor exists. Recommended: the Modal clock, not monitors. There are **no daily cost caps** yet: a
      night of the clock as it is costs about 260 Context.dev credits for fetching, plus up to hundreds or
      1000+ more if auto-tracing and specimen tracing find much (each trace is 15 to 25 credits). Proposed
      but **not built**: daily caps on Context.dev credits and Gemini calls stored in Postgres; switches
      `CLOCK_TRACING=0` and `CLOCK_FEEDS=lemmy`; sending `VISION_PER_TICK` and `AUTO_TRACES_PER_TICK` to
      Modal (`deploy.py` sends neither today); a staging deploy with its own database restored from a
      dump. Also set a budget alert on the Gemini key and a Modal spending limit.
- [ ] **Week backfill** (`scripts/backfill.py`, not run; Lemmy only, so no Context.dev credits, about 120
      Gemini image calls). Besides filling "this week", it is what gives "Rising today" its history: the
      backfilled posts are dated by when they were posted, so the 3-day rule is met at once.
- [ ] "New specimens" lists memes added to the archive in the last 7 days, which includes old templates
      such as This Is Fine (2013). Undecided whether to relabel it or show only recent memes.
- [ ] Context.dev monitors and the webhook signing secret (see `claude_docs/STATUS.md`).
- [ ] The Imgflip top-100 step of the seed.
