# Staging backup: a frozen copy of the site and the data for the demo

Date: 2026-11-14. Branch: `feat/staging-backup` (from `main` at 1b83c5a). Status: code written and
tested; nothing created or deployed yet. The commands at the end are for the main session.

## Goal

Tonight production collects and labels memes live (branch `feat/night-run`). Tomorrow on stage we
want a known-good copy of the site and the data that we can switch to if the night run pollutes the
data, breaks the site, or runs out of budget. The copy must never spend Context.dev credits or
Gemini calls and must not be able to write to production.

## Options weighed

| Option | Cost | Setup | Verdict |
|---|---|---|---|
| (a) second database `memepedia_staging` in the same Aiven service, filled by a copy script | none (same plan; the archive is about 10 MB) | one `CREATE DATABASE` (avnadmin has `CREATEDB`; checked read-only) | **chosen**, combined with (d) |
| (b) separate Aiven service | money, console signup, new connection string | slow | no: nothing it buys that (a) does not |
| (c) staging app on a local or other Postgres | free | Modal cannot reach the laptop's Postgres; another hosted Postgres means another signup | no |
| (d) staging app frozen (no clock, no webhook work, no paid calls) | none | small code change | **chosen**, on top of (a) |

Why (a) + (d): it needs no new account, no new secret in `.env` (the staging URL is derived from
`DATABASE_URL` by swapping the database name), and Modal already deploys a second app under
`MEMEPEDIA_APP=memepedia-staging`. Before this branch, though, that second app used **production's
database and both paid keys**, so it was a second writer on production, not a backup. This branch
makes it a frozen copy.

Fallback if Aiven ever refuses `CREATE DATABASE` (not expected): add the database in the Aiven
console (service, Databases tab, name `memepedia_staging`), then run the clone without `--create`.

## The design

### Four independent locks on the staging copy

1. **Its own database.** `deploy.py` gives a non-live app (any `MEMEPEDIA_APP` other than
   `memepedia`) a secret holding exactly two values: `DATABASE_URL` = the staging database
   (`STAGING_DATABASE_URL` if set, else `memepedia_staging` on production's server) and
   `MEMEPEDIA_READ_ONLY=1`. Production's URL never reaches the staging container. The deploy is
   refused if the staging URL resolves to production's database (same host, port and name).
2. **No paid keys at all.** `CONTEXTDOTDEV_KEY`, `GEMINI_KEY` and the webhook secret are not sent,
   so even a bug cannot spend credits: the clients have nothing to authenticate with.
3. **Read-only API.** With `MEMEPEDIA_READ_ONLY=1`, every non-GET/HEAD/OPTIONS route under `/api/`
   answers 503 with "This is a read-only backup copy of Memepedia: tracing and uploads are off."
   (the frontend shows the `error` text). That covers `/api/trace`, `/api/identify`,
   `/api/proposals` and `/api/webhooks/context`. The app also skips `init_schema()` at startup.
   No clock: `deploy.py` already never schedules the clock on a non-live app, regardless of
   `MEMEPEDIA_CLOCK`. No Context.dev monitor points at the staging URL.
4. **Read-only database.** `clone_db.py --freeze` runs
   `ALTER DATABASE memepedia_staging SET default_transaction_read_only = on`, so every later session
   on it is read-only; any write fails in Postgres itself. GET routes only read (checked), and the
   pool's `SET TIME ZONE` is allowed in a read-only transaction (tested). The clone script switches
   this off for its own session only, so refreshing the copy still works.

Residual risk, accepted for a hackathon: the staging URL uses the same `avnadmin` credentials as
production, so code running in the staging container *could* in principle connect to `defaultdb`.
Locks 2 and 3 mean no code path does. A dedicated Aiven user limited to `memepedia_staging` would
close this; not worth doing tonight.

### The copy script: `backend/scripts/clone_db.py`

```
uv run python scripts/clone_db.py --source SRC --target DST [--create] [--freeze] [--dry-run] [--restore]
```

- Databases are named, never typed: `production` (DATABASE_URL), `staging`
  (STAGING_DATABASE_URL, else `memepedia_staging` next to production), `db:NAME` (database NAME on
  production's server), `env:NAME` (any variable). No connection string appears on the command line,
  in shell history, or in output; databases are printed as e.g.
  `database 'memepedia_staging' on *.aivencloud.com:15330`, and host names are masked in errors.
- The source is read inside one `REPEATABLE READ`, read-only transaction, so all four tables come
  from the same instant even while the night run is writing.
- The target gets `schema.sql` (idempotent), then `TRUNCATE history, sightings, links, nodes` and a
  `COPY` per table (ids preserved) **in one transaction**: a failed copy leaves the target as it
  was. The `history` id sequence is moved past the highest copied id.
- Row counts of both sides are printed, and the script fails if they differ afterwards.
- Refusals (exit 2, nothing written): source and target are the same database (credentials
  ignored); the target is production or is named `defaultdb`, unless `--restore`; `--restore` with a
  target that is not production; `--restore --freeze`; an unreadable connection string; a source
  missing a table or with no nodes (an empty or broken database is never copied over anything); a
  source column the target schema lacks (run from a branch whose `schema.sql` has it).
- `--restore` (staging back over production) also asks for the database name (`defaultdb`) to be
  typed, and first saves production's rows to `backend/.data/before_restore_<UTC stamp>.json`.

Verified: the full suite passes (321 tests, 22 of them new in `backend/tests/test_clone_db.py`);
Ruff and `mypy memepedia scripts` are clean. A real read-only run copied production (133 nodes,
151 links, 425 sightings, 88 history at the time) into a local database with matching counts;
`--target production` without `--restore` was refused.

### Files changed

- `backend/memepedia/staging.py` (new): staging database name, URL derivation, `same_database`,
  masked `describe`.
- `backend/scripts/clone_db.py` (new): the copy and restore.
- `backend/tests/test_clone_db.py` (new).
- `backend/memepedia/config.py`: `read_only` setting from `MEMEPEDIA_READ_ONLY`.
- `backend/memepedia/api.py`: the read-only middleware (one block after `app = FastAPI(...)`) and
  `init_schema()` skipped when read-only.
- `backend/deploy.py`: `_staging_values()` plus a three-line branch in `_secret()`; docstring.
  The clock code is untouched, so this should merge cleanly with `feat/night-run`.

## Commands for the main session

Run in WSL from **this branch's** `backend/`, i.e.
`/home/logis/work/Hackathons/Junction2026/meme-genealogy/.claude/worktrees/agent-a7eb21e3907c6661b/backend`
(it has a Linux `.venv`), or from any checkout of `feat/staging-backup`. The script reads the repo
root's `.env`, so link it first (git-ignored; remove it again before committing).

> **Warning.** Deploy the staging app only from a checkout that has this branch's `deploy.py`.
> From `main` as it is today, `MEMEPEDIA_APP=memepedia-staging` would give the copy production's
> database and both paid keys. And never run `modal deploy` from this branch **without**
> `MEMEPEDIA_APP` set: that would replace the live app with this branch's code.

| # | Step | Command | Cost | Reversible? |
|---|---|---|---|---|
| 0 | Link `.env` into the worktree | `ln -s /home/logis/work/Hackathons/Junction2026/meme-genealogy/.env ../.env` | free | yes: `rm ../.env` |
| 1 | Create the staging database, copy production into it, freeze it | `uv run python scripts/clone_db.py --source production --target staging --create --freeze` | free (same Aiven plan, ~10 MB). Production: one read-only snapshot of about a second | yes: see teardown |
| 2 | Build the site | `cd ../web && npm ci && VITE_API_BASE= npm run build && cd ../backend` | free | n/a |
| 3 | Deploy the staging app | `MEMEPEDIA_APP=memepedia-staging uv run --with modal modal deploy deploy.py` — check it prints `Staging copy reads database 'memepedia_staging' ... read-only, with no Context.dev or Gemini key.` | Modal compute only while requested (no warm container, scales to zero after 5 min): cents | yes: `modal app stop memepedia-staging` |
| 4 | Verify | see below | free | n/a |

Step 4, verify (the staging URL is printed by step 3; by Modal's naming it should be
`https://aleksandr-shishkov-work--memepedia-staging-web.us-east.modal.run`):

```bash
STAGING=https://aleksandr-shishkov-work--memepedia-staging-web.us-east.modal.run
PROD=https://aleksandr-shishkov-work--memepedia-web.us-east.modal.run
curl -s $STAGING/api/health   # counts must equal step 1's "target after" line
curl -s $PROD/api/health      # equal at first; drifts upward once the night run collects
curl -s -o /dev/null -w '%{http_code}\n' $STAGING/                # 200, the site
curl -s -o /dev/null -w '%{http_code}\n' "$STAGING/api/wall"      # 200
curl -s -X POST -H 'content-type: application/json' -d '{"query":"Doge"}' $STAGING/api/trace
# -> 503 {"error":"This is a read-only backup copy of Memepedia: tracing and uploads are off."}
```

Then open `$STAGING` in a browser: wall, archive, a family tree (e.g. `/meme/doomer`).

### Refreshing the copy (optional, e.g. in the morning if the night run went well)

| Step | Command | Cost | Reversible? |
|---|---|---|---|
| Keep last night's frozen copy under another name first | `uv run python scripts/clone_db.py --source staging --target db:memepedia_backup --create --freeze` | free | yes (drop it) |
| Refresh staging from production | `uv run python scripts/clone_db.py --source production --target staging --freeze` | free; the staging site shows the new data at once, no redeploy | yes: clone `db:memepedia_backup` back into `staging` |

### Switching the demo on stage

Pick by what went wrong.

**A. Show the staging site** (production is broken, slow, or out of budget). Open the staging URL
instead of the production one; warm it about a minute before (it has no warm container, so the
first request after 5 idle minutes waits on a cold start). Wall, archive, trees and "related" work;
trace, identify and proposals show the read-only message. Cost: free. Reversible: instantly, just
go back to the production URL.

**B. Put the copy back into production** (the site works but the night run polluted the data, and
we want the production URL with live trace). In order:

| # | Step | Command | Cost | Reversible? |
|---|---|---|---|---|
| B1 | Stop every writer on production: the clock (redeploy production with `MEMEPEDIA_CLOCK` unset, from the branch that is live, or whatever off-switch `feat/night-run` provides) and any Context.dev monitors (`uv run python scripts/monitors.py delete`) | as written | free | yes: redeploy with the clock on |
| B2 | Keep the night's data to inspect later | `uv run python scripts/clone_db.py --source production --target db:memepedia_night --create` | free | yes (drop it) |
| B3 | Restore: replace production's rows with the staging copy; type `defaultdb` when asked | `uv run python scripts/clone_db.py --source staging --target production --restore` | free; production's rows also saved to `backend/.data/before_restore_*.json` | yes: `--source db:memepedia_night --target production --restore` |
| B4 | Check | `curl -s $PROD/api/health` shows the staging counts | free | n/a |

A `--dry-run` of B3 first prints both sides' counts and writes nothing. If the night run added a
column to production's schema, B3 still works (production keeps the column, copied rows get its
default); B2 must then run from a checkout whose `schema.sql` has that column, or it refuses.

### Teardown (after the demo)

| Step | Command | Cost | Reversible? |
|---|---|---|---|
| Stop the staging app | `modal app stop memepedia-staging` | free | yes: redeploy (step 3) |
| Drop the copies | `uv run python -c "import psycopg; from memepedia.config import get_settings; c = psycopg.connect(get_settings().database_url, autocommit=True); [c.execute(f'DROP DATABASE IF EXISTS {n} WITH (FORCE)') for n in ('memepedia_staging', 'memepedia_backup', 'memepedia_night')]"` | free | **no**, the copies are gone (production is untouched: a session cannot drop the database it is connected to, `defaultdb`) |
| Remove the `.env` link | `rm ../.env` | free | yes |

## Not done, on purpose

- No change to `deploy.ps1`: it passes `MEMEPEDIA_APP` through the environment already.
- No STATUS.md edit, to avoid conflicts with the other branches; the main session should add a
  line under "Running the backend" when it merges this.
- The staging app keeps the image's `min_containers=0`. If a cold start on stage is a worry, warm
  it as in A, or deploy it with a warm container (a one-word change in `deploy.py`, small cost).
