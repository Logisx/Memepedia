# To do: things only someone with the repo-root `.env` can do

## Rollout 2026-11-15: Gemma guardrail, duplicates, a stamp on every tile, posts in the tree

Branch `bugfix/final-fixes` (commits `11add3f` to the Part E commit; plan:
`claude_docs/plans/2026-11-15_dedupe-stamps-tree_plan.md`). Everything below runs from `backend/` with
the repo-root `.env`, so it hits **production**. Do the steps in order and keep every output file in
`backend/.data/` (git-ignored). Paid calls in total: at most ~160 Gemini/Gemma calls (step 5: 80
images, two calls each) plus an optional ~300 (step 7); **no Context.dev credits**.

What it changes, in one line each:
- The NSFW verdict comes from a separate Gemma call (`GUARDRAIL_MODEL`, default `gemma-3-27b-it`);
  Gemini still labels the meme. **Never called with the real key yet** (step 0 checks it).
- Every image is read: GIF, AVIF and WebP are converted, Reddit preview thumbnails become the full
  image, Lemmy proxy links are unwrapped. A failed image records why (`look_error`).
- Every wall tile has a stamp: `family: …`, `unidentified`, `one-off` (looked at, not a template) or,
  with NSFW on, `not read yet`. Expired specimens' memes go back to `unidentified`.
- Reposts (same picture, another URL) are saved but hidden, cost no vision call and share the
  original's stamp.
- A post whose title names a meme outright ("POV: you're Jensen Huang") is stamped with it
  (`VISION_MATCH_TITLES=0` turns that off).
- A meme's page shows up to 48 posts, including a character's appearances inside other templates,
  drawn as groups under the meme in its family map.

### 0. Before touching anything
- [ ] Back up production: `pg_dump -Fc "$DATABASE_URL" -f .data/before_dedupe_2026-11-15.dump`
      (where `pg_dump` lives: see "Earlier rollout", step 0).
- [ ] `git fetch && git checkout bugfix/final-fixes && git pull`, then `uv sync` (adds Pillow).
- [ ] `uv run pytest -q`, `uv run ruff check .`, `uv run mypy memepedia scripts` on Linux/WSL; expect
      **412 passed**. On WSL the test database cannot live on `/mnt/c`: copy the repo into the WSL
      filesystem first (`rsync -a --exclude .venv --exclude .pgdata --exclude node_modules
      /mnt/c/.../Memepedia/ ~/memepedia-wsl/`) and run there.
- [ ] AVIF support: `uv run python -c "from PIL import features; print(features.check('avif'))"`
      should print `True`.
- [ ] Gemma works with the key: `uv run python scripts/smoke_llm.py`. The
      `label_nsfw_only (guardrail: gemma-3-27b-it)` block must print a verdict such as `(False, None)`,
      not an error. If the model is not found, list what the key offers:
      `uv run python -c "from memepedia import llm; print([m.name for m in llm._get_client().models.list() if 'gemma' in m.name])"`
      and set `GUARDRAIL_MODEL=<one of those, without the models/ prefix>` in `.env`.
- [ ] `uv run python scripts/budget.py status`: note the Gemini calls in the last 24 h.
- [ ] Read-only snapshot **before** anything changes (no writes, no paid calls, works before the
      deploy): `uv run python scripts/diagnose.py --name "Jensen Huang" | tee .data/diagnose_before.txt`.
      Send this file to the owner: it shows what the vision model said about every Jensen Huang post
      that is not stamped with him.

### 1. Get the code live
- [ ] Get the branch merged into `main` (owner's OK), then `git checkout main && git pull`.
- [ ] Optional `.env` switches (defaults shown; `deploy.py` sends them to Modal):
      `GUARDRAIL_MODEL=gemma-3-27b-it`, `VISION_MATCH_TITLES=1`.
- [ ] Deploy from an up-to-date `main`: `.\backend\deploy.ps1` (Windows) or the Linux/WSL steps in
      "Earlier rollout", step 2. The new columns (`look_error`, `duplicate_of`, `fingerprint`) are
      added on the first start; that is additive and safe for the old rows.
- [ ] Check: `<PUBLIC_BASE_URL>/api/health` is 200; the wall loads and every tile has a stamp.

### 2. Mark the reposts already in the archive (no paid calls, ~750 image downloads)
- [ ] Dry run. It also saves each image's fingerprint (or why it could not be read), which is safe:
      `uv run python scripts/dedupe.py | tee .data/dedupe_dry.txt`. Expect roughly 10 to 20 groups.
- [ ] Open 5 groups from the output and check each really is one picture. If any is not, stop and
      tell the owner (the thresholds in `memepedia/dedupe.py` need tightening).
- [ ] `uv run python scripts/dedupe.py --apply | tee .data/dedupe_apply.txt`.
- [ ] On the wall, the cross-posted "Fall Guy", "Oh, behave!" and "It had a good run" now show once.

### 3. Give expired specimens' memes their "unidentified" stamp back (no paid calls)
- [ ] `uv run python scripts/relook.py --orphans` (dry run, lists them), then add `--apply`.

### 4. Images that were never read: dry run (no paid calls)
- [ ] `uv run python scripts/relook.py | tee .data/relook_dry.txt`. Most rows should now say `ok`
      (the GIFs, AVIFs and Reddit thumbnails); the rest are listed by reason.

### 5. Read them for real (at most 80 images = 160 calls)
- [ ] `uv run python scripts/relook.py --apply --max 80 | tee .data/relook_apply.txt`. It stops by
      itself, saying so, if the Gemini cap is reached.

### 6. Re-match pending posts, now with the title rule (no paid calls)
- [ ] `uv run python scripts/rematch.py | tee .data/rematch_dry.txt`. Read the `title` lines hardest:
      open about 10 of those posts and check the stamp is right.
- [ ] `uv run python scripts/rematch.py --apply`.

### 7. Optional: re-label old "not a meme" posts with the looser prompt (at most ~150 images)
- [ ] `uv run python scripts/relook.py --not-memes` (dry run, lists them), then
      `uv run python scripts/relook.py --not-memes --apply --max 150`.
- [ ] Then step 6 again.

### 8. Check, record, hand back
- [ ] `/meme/jensen-huang`: under the Jensen Huang card the family map shows dotted post boxes
      ("in the wild", plus one per other template he appears in) instead of "No relatives on record".
      Clicking a box filters the Sightings tab; a box naming another meme opens that meme. The
      Sightings tab lists more than 12 posts.
- [ ] `uv run python scripts/diagnose.py --name "Jensen Huang" | tee .data/diagnose_after.txt` and
      send both diagnose files to the owner.
- [ ] Watch a few live ticks in the Modal logs: `TickReport(...)` now ends with `duplicates=`; a
      cross-post shows up there instead of as a second tile. A few `nsfw guardrail failed` lines are
      fine (that post keeps Gemini's verdict); one on every post means Gemma is not answering: fix
      `GUARDRAIL_MODEL` and redeploy.
- [ ] Each post now costs about two Gemini-counted calls (label plus guardrail). Check
      `uv run python scripts/budget.py status` the next morning.
- [ ] Optional: label the still-unlabelled images with Gemma: `uv run python scripts/label_nsfw.py --dry-run`,
      then without `--dry-run`. `--relabel` re-judges **every** node and sighting (about 850 calls); only
      if the owner wants Gemma's verdict on the whole archive.
- [ ] Update `claude_docs/STATUS.md` ("Done") with the numbers from steps 2 to 7.

### If something looks wrong
- Wrong title stamps: set `VISION_MATCH_TITLES=0` in `.env`, redeploy, and tell the owner which posts.
- Wrong duplicates: `UPDATE sightings SET duplicate_of = NULL WHERE id IN (...)` for the bad ones (their
  stamp stays as the keeper's; run `scripts/rematch.py` afterwards for the pending ones). Last resort:
  restore the step-0 dump (`pg_restore --clean -d "$DATABASE_URL" <dump>`), which loses everything
  collected since.
- Gemma not answering at all: `GUARDRAIL_MODEL=gemini-3.8-flash` makes the guardrail use Gemini again.

## Earlier rollout (2026-11-14, kept for reference)

Last checked against the branch on 2026-11-14 (up to commit `fa2bcb2`). A Claude session can do all of
this by following `claude_docs/plans/2026-11-14_stamping-rollout_plan.md`. Anything run from `backend/`
with a `.env` holding `DATABASE_URL` hits the **hosted production database**. Do the steps in order.

### What is on `bugfix/various-fixes` and not yet live

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

### 0. Before touching anything

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

### 1. Put the new families in the archive

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

### 2. Get the code live

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

### 3. Measure, then re-match old posts

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

### Still open (not part of this branch)

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
