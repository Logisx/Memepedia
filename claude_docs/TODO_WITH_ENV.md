# To do: things only someone with the repo-root `.env` can do

Written 2026-11-14. These steps cover the stamping change (branch `bugfix/various-fixes`) and the
new seed families. Anything run from `backend/` with a `.env` holding `DATABASE_URL` hits the
**hosted production database**. Do the steps in order.

Needs on that machine: `uv`, `.env` at the repo root, Modal access to the
`aleksandr-shishkov-work` workspace, `gh` or the GitHub site for the PR. Run the tests on Linux/WSL
(they cannot run on Windows).

## 0. Before touching anything

- [ ] Back up production: `pg_dump -Fc "$DATABASE_URL" -f backend/.data/before_stamping_<date>.dump`
      (git-ignored). **Why:** the seed's `families` step overwrites every seed node's name,
      **aliases**, kind, dates and summary with the values in `seed.json`. Aliases the resolver
      learned since the last seed would be lost for all ~100 seed nodes. The dump lets you restore
      them. If that matters, copy the aliases out first (`SELECT id, aliases FROM nodes`).
- [ ] Note the Context.dev credit balance (dashboard) and `backend/.data/credits.jsonl` total.
- [ ] `git pull` on `bugfix/various-fixes`; from `backend/` run `uv run pytest -q`, `uv run ruff check .`,
      `uv run mypy memepedia scripts`. Expect 5 known failures in `tests/test_trace.py` (they call
      Gemini; with a key in `.env` they may pass instead).

## 1. Put the new families in the archive

- [ ] `uv run python scripts/seed.py --steps families` (adds 19 nodes and 43 links; new links start as
      "inferred", shown dashed). It also promotes Sad Baby Yoda, IQ Bell Curve, Rickroll and Gru's Plan
      from `specimen` to `established` on purpose (specimens with no recent sightings start being
      deleted on 2026-11-21).
- [ ] `uv run python scripts/seed.py --steps images`: finds an image for every node that has none. Expect
      a few misses among the AI-character nodes; check the next step.
- [ ] Open the site and look at each new family: Italian Brainrot, Skibidi Toilet, Grimace, That's Not
      Cinema, Moo Deng, Despicable Me, Baby Yoda, Duckroll, Labubu, and Wojak (IQ Bell Curve). Check
      each has an image, a sensible family map, and no "No relatives on record" message. Set images by
      hand for any that are missing.
- [ ] Optional, costs credits (about 6 to 7 per link, roughly 250 to 300 for all 43): turn links into
      cited ones. **Always narrow it with `--families`.** Without it `verify` re-checks every inferred
      link in the archive, including ones that already failed (about 85 credits were wasted that way
      before). Demo families first:
      `uv run python scripts/seed.py --steps verify --families italian-brainrot,skibidi-toilet,despicable-me`
      then the others (`grimace,not-cinema,moo-deng,baby-yoda,duckroll,labubu`).
- [ ] Hand-check the `uncertain` dates the new nodes carry (Skibidi Cameraman/TV Man/"Skibidi", Tung Tung
      Tung Sahur, Ballerina Cappuccina, Minion Memes); their `check_note` says what is unconfirmed.

## 2. Get the code live

`main` is protected. Merge only with the owner's explicit OK.

- [ ] Open a PR from `bugfix/various-fixes` into `main` and get it merged (owner's OK).
- [ ] `git checkout main && git pull`. Deploy **only from an up-to-date `main`**, because `modal deploy`
      replaces the whole app.
- [ ] Optional dry run first: `$env:MEMEPEDIA_APP = "memepedia-staging"` then `.\backend\deploy.ps1`.
      Note the staging copy uses the same `DATABASE_URL`, so it reads and writes production data.
      Remove it with `modal app stop memepedia-staging`.
- [ ] `.\backend\deploy.ps1` for the real deploy. Check `https://aleksandr-shishkov-work--memepedia-web.us-east.modal.run/api/health`.
- [ ] Optional settings in `.env` before deploying (defaults shown; `deploy.py` now sends them to Modal):
      `VISION_EXACT_MIN_CONFIDENCE=0.7`, `VISION_MIN_CONFIDENCE=0.85`, `VISION_MATCH_SUBJECTS=1`.
      To switch subject matching off: set `VISION_MATCH_SUBJECTS=0` and redeploy.

## 3. Measure, then re-match old posts

- [ ] Run the two queries from `claude_docs/plans/2026-11-14_identification-recall_plan.md` ("After it
      lands"): where posts drop out, and which subjects recur among pending posts.
- [ ] Add the recurring real subjects (Jensen Huang for the Nvidia memes, and so on) to `seed.json` as
      `kind: "character"` nodes with a format link, check their facts, then step 1 again
      (`--steps families,images`).
- [ ] Dry run: `uv run python scripts/rematch.py` (no Gemini calls, changes nothing). It prints the target
      database first; confirm it is the one you mean.
- [ ] Read the list, open about 20 of the posts, and check the matches are right. Look hardest at the
      `subject` ones.
- [ ] `uv run python scripts/rematch.py --apply`.
- [ ] Optional, spends Gemini calls: add `--llm --max-llm 50` (dry run first, then with `--apply`).
- [ ] If stamping looks wrong afterwards: raise `VISION_EXACT_MIN_CONFIDENCE`, or set
      `VISION_MATCH_SUBJECTS=0`, and redeploy.

## Still open from elsewhere (not part of this change)

- [ ] Overnight clock: the Modal clock is paused (`MEMEPEDIA_CLOCK` unset). Decide whether to run it
      overnight and on which cost caps. Not yet decided or checked: the per-tick Gemini cap is
      `VISION_PER_TICK` (10) and auto-traces are `AUTO_TRACES_PER_TICK` (1), but `deploy.py` sends neither
      to Modal, and I found no daily Context.dev credit cap in the code.
- [ ] Context.dev monitors and the webhook signing secret (see `claude_docs/STATUS.md`).
- [ ] The week backfill and the Imgflip top-100 step.
