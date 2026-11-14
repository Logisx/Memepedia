# Plan: the overnight collection run (Context.dev monitors first, Modal clock as fallback)

Written 2026-11-14 evening. Code on branch `feat/night-run` (from `main` at 1b83c5a). Read
`claude_docs/STATUS.md` first. Nothing in this plan has been run against production yet.

## State at the time of writing (read-only checks)

- **No Context.dev monitor exists.** `GET /monitors` returned an empty list; `GET /monitors/limits`
  says 0 of 5000 used, plan "free", **50,000 credits remaining**.
- Modal app `memepedia` is deployed (since 17:15 EET). The clock is paused: `/api/health` still shows
  425 sightings, the same as after the NSFW deploy.
- No `CONTEXTDEV_WEBHOOK_SECRET` and no `MEMEPEDIA_CLOCK` in `.env`. With the code on `main`, the
  webhook would accept any caller and each call could trigger a paid feed fetch.

## Design

**Primary: 16 Context.dev page monitors**, one per feed, every 10 minutes (the minimum). Each run is
delivered to `https://aleksandr-shishkov-work--memepedia-web.us-east.modal.run/api/webhooks/context` as a
signed `run.completed` event. Every run is delivered, not only changed ones, for two reasons: the
receiver counts each run's credits (`data.run.credits_charged`), and the deliveries double as a
heartbeat. The receiver ticks the feed only when `data.change` is not null, so an unchanged page costs
no fetch and no Gemini call.

**Fallback: the Modal clock**, deployed with `MEMEPEDIA_CLOCK=1`. Every minute it checks the heartbeat
(`app_state.last_webhook`). While an authenticated delivery arrived in the last 20 minutes
(`MEMEPEDIA_CLOCK_FALLBACK_MINUTES`), it does nothing. Otherwise it ticks one feed in rotation, exactly
as before. It needs no switch: it covers the case where monitors cannot be created, deliveries are
refused, or the monitors are paused.

Both paths go through `live.guarded_tick`. It checks the cost guards first, then a per-feed throttle
(at most one tick per feed per 5 minutes, whoever asks), then ticks, then runs `maintenance` (specimen
clustering and expiry, at most every 15 minutes; before this change only the clock ran it).

**Why monitors first:** the owner asked for it, and it is the challenge's story (the web, watched by
Context.dev, pushes into our database). It costs about 6 times what the clock costs (see below), but
both are a few percent of the balance. The clock costs nothing extra while it is idle, apart from a
few seconds of Modal compute per minute.

### Webhook security (`api.post_context_webhook`, `live.authentic`)

- Context.dev issues **one signing secret per monitor**. You do not pick it, and there is no account-wide
  secret. It comes back as `webhook.secret` when the monitor is created. `scripts/monitors.py create`
  stores it in the new `webhook_monitors` table (monitor id, feed key, secret) and never prints it.
  If the response has no secret, the script asks for one through the rotate-secret endpoint.
- The route reads the monitor id from the body, looks up that monitor's secret, and checks
  `X-Context-Signature` (HMAC-SHA256 of `t.body`, 5-minute tolerance). `CONTEXTDEV_WEBHOOK_SECRET`, if
  set, is also accepted. **With no secret held, every delivery gets a 401.** The old behaviour, where a
  missing secret meant "accept anyone", is gone.
- Event ids are deduplicated in Postgres (`webhook_events`), so this holds across containers and
  restarts. Bodies larger than 2 MB get a 413. The route takes 120 calls per minute per container,
  then answers 429. Each monitor's feed is ticked at most every 5 minutes.
- What the secret is, for the owner: a shared key between Context.dev and us. Context.dev signs every
  delivery with it, and we recompute the signature, so only Context.dev can make us spend money.

### Cost guards (`memepedia/budget.py`, shared through Postgres)

| Kind | Counted where | Hard cap per rolling 24 h | Background stops at |
|---|---|---|---|
| `contextdev` (credits) | every scrape, search, monitor create/run (the `X-Credits-Used` header), plus each delivered monitor run (`credits_charged`) | 3000 | 2500 |
| `gemini` (calls) | every `llm._generate` attempt, retries included | 5000 | 4500 |
| `traces` (count) | traces the background loop starts (auto-trace and specimen clustering) | 10 | 10 |

- Caps come from the database (`scripts/budget.py cap KIND N`, no redeploy needed), else the
  environment (`MEMEPEDIA_CAP_CONTEXTDEV`, `MEMEPEDIA_CAP_GEMINI`, `MEMEPEDIA_CAP_TRACES`), else these
  defaults. The window is a rolling 24 hours (hourly buckets), so a 10-hour night falls inside one
  window no matter when midnight is.
- "Background stops at": ticks and the backfill stop 500 short of the hard cap. That keeps a reserve,
  so visitors' traces and identifications still work in the morning. The chokepoints in
  `contextdev` and `llm` refuse every call once the hard cap is reached. They raise `CreditCapReached`
  and `GeminiCapReached`, subclasses of the errors callers already handle.
- **Kill switch:** `scripts/budget.py off` (DB flag, instant, no redeploy) or `MEMEPEDIA_PAID_OFF=1`
  (env, needs a redeploy). It refuses all paid work. Pages are read-only and keep working, and so do
  the wall and the archive.
- **When a background cap is hit, or the kill switch is on:** the tick is skipped with a log line. The
  memepedia monitors are paused through the free PATCH endpoint (at most every 30 minutes), because
  each monitor run costs a credit whatever we do with it. The clock then sees no heartbeat, wakes up,
  and is refused by the same guard. To restart: raise the cap or turn the switch on, then run
  `monitors.py resume`.
- `/api/health` now also reports `paid_work` ("allowed" or the reason it is blocked) and
  `last_webhook_s`.
- Known gap, accepted: the check and the spend are not one transaction, so concurrent workers can
  overshoot a cap by the few calls in flight (at most about 4 threads per tick).

## Cost estimate for ~10 hours

**Context.dev** (per the docs: a page monitor run costs 1 credit, a scrape costs 1 credit base,
monitor management and webhook deliveries are free; Lemmy is read directly and costs nothing):

| Item | Per hour | 10 hours |
|---|---|---|
| Monitor runs: 16 monitors x 6 runs | 96 | 960 |
| Baseline runs at creation | – | 16 |
| Fetches on change: 5 Reddit RSS + 2 Imgflip feeds x 6 = 42 scrapes of 1 credit (Lemmy free) | <= 42 | <= 420 |
| Background traces, capped at 10 per 24 h, ~10-25 credits each (search plus verification) | – | <= 250 |
| **Total** | | **~1,400-1,650** (about 3% of the 50,000 balance; the guard stops background work at 2,500) |
| Clock-only alternative, for comparison: 7 paid feeds per 16-minute rotation | ~26 | ~260 |

**Gemini** (`gemini-3.8-flash`; at most 10 images per tick):

- Expected fresh images per 10-minute run: Reddit about 6 per feed, Imgflip about 10 per feed, Lemmy
  about 1 per community. That is (5x6 + 2x10 + 9x1) x 6, about **350 vision calls an hour**. Add near-match
  name checks (~10%), clustering (4 an hour) and up to 10 traces (~5 calls each): about **400 an hour,
  ~4,000 for the night**. The theoretical maximum is 16 x 6 x 10 = 960 vision calls an hour, and the
  guard stops background work at 4,500 calls.
- Money, **assumed and not verified**: about 3k input tokens (image plus prompt with the archive's names)
  and about 300 output tokens per call. At Flash-class prices ($0.30-0.50 per million tokens in,
  $2.50-3 per million out) that is about $0.002 a call, so **~$7-10 for the night, at most ~$12 at the
  5,000 cap**. Check the real price and tier in Google AI Studio. On a free tier, the daily request
  limit would show up as 429s. Ticks then log errors and the posts stay unseen until a later tick.

**Week backfill:** **0 Context.dev credits** (Lemmy API). At most 200 vision calls plus ~20 name checks,
about 220 Gemini calls (~$0.50), counted against the same Gemini budget.

## The backfill: run it tonight, yes

- "Rising today" requires the archive to have been collecting for at least 3 days, measured as
  `min(seen_at)`. Production started collecting on 2026-11-14, so without the backfill the strip
  stays empty until 2026-11-17, after the demo. `backfill.py` inserts sightings with `seen_at = posted_at`,
  up to 7 days back, which unlocks it straight away. It also adds sighting counts for the week.
- It does not guarantee that anything rises. A meme still needs 3 or more distinct posts in 24 hours at
  2 or more times its prior daily rate, and only about 10% of Lemmy posts get a stamp. The night's Reddit
  and Imgflip volume is what feeds the 24-hour count. It does not create specimens (no tracing), so it
  does not change "New specimens".
- Run it **before** creating the monitors, with `--max-images 200` (the script's maximum). It now refuses
  to run, or trims its batch, when the Gemini budget is short. It prints its target database first.

## Production steps, in order (main session / owner)

Each step lists its cost and whether it can be undone. Run commands from `backend/` with uv. On WSL, use
`UV_PROJECT_ENVIRONMENT` outside the repo, as STATUS says.

1. **Merge `feat/night-run` into `main`** (owner's explicit OK, since `main` is protected). Merge with
   `feat/staging-backup` first if it is ready. The overlap in `backend/deploy.py` is the `SENT` tuple (7
   names added) and the body of `clock()`, which now calls `live.clock_tick`. Free. Reversible (git).
2. **Back up the production database** (`pg_dump -Fc "$DATABASE_URL" > backend/.data/before_night_run.dump`,
   or the staging agent's backup procedure). Free. It is what makes steps 6-8 reversible.
3. **Set `MEMEPEDIA_CLOCK=1` in the repo-root `.env`.** This schedules the fallback clock. Optional: cap
   overrides `MEMEPEDIA_CAP_*` (the database overrides can do the same later without a redeploy).
   **Do not create a webhook secret:** Context.dev generates one per monitor in step 8. Free. Reversible.
4. **Build and deploy:** from `web/` run `VITE_API_BASE= npm run build`, then from `backend/` run
   `uv run --with modal modal deploy deploy.py` (or `.\backend\deploy.ps1` on Windows). App startup
   creates the four new tables (`spend`, `app_state`, `webhook_monitors`, `webhook_events`). The clock
   starts ticking right away, because no heartbeat exists yet: about 26 credits an hour until step 8.
   Costs Modal compute only. Reversible: redeploy the previous `main`.
5. **Verify the deploy:**
   - `curl -s <URL>/api/health` should show `"paid_work":"allowed"` and `"last_webhook_s":null`.
   - `curl -s -o /dev/null -w '%{http_code}' -X POST <URL>/api/webhooks/context -d '{}'` should print
     **401**, which proves the webhook now refuses unsigned callers.
   - `uv run python scripts/budget.py status` shows the caps and spend. It prints the target database;
     it should say aivencloud.
   Free.
6. **Week backfill:** `uv run python scripts/backfill.py --max-images 200`. 0 credits, about 220 Gemini
   calls. It writes sightings to production. It can only be undone by restoring the backup from step 2.
7. **Monitor dry run:** `uv run python scripts/monitors.py create --dry-run`. It lists the 16 monitors
   (Lemmy community pages, Reddit `/new/.rss`, Imgflip `?sort=latest`), each with `run.completed` going
   to the webhook. It makes only free list calls. Free.
8. **Create the monitors:** `uv run python scripts/monitors.py create`. It prints
   `created ...: id=..., secret stored` 16 times and never prints a secret. Rerunning it creates only the
   missing ones. It costs 16 credits now, then about 96 an hour for the runs plus up to 42 an hour for
   fetches. Reversible: `monitors.py pause` (stops all cost, keeps the secrets) or `monitors.py delete`.
9. **Verify it works** (after 10-15 minutes):
   - `uv run python scripts/monitors.py list` shows 16 `memepedia:` monitors with `status=active`.
   - `curl -s <URL>/api/health` shows `last_webhook_s` below about 600 and a rising `sightings` count.
   - `uv run python scripts/budget.py status` shows contextdev spend rising by about 1.6 a minute and
     "last monitor webhook: x min ago".
   - `uv run --with modal modal app logs memepedia` shows `TickReport(...)` lines from the web function
     and `idle: a monitor webhook arrived ...` from the clock.
   - `curl -s '<URL>/api/wall?limit=5'` shows new sightings.
   - **If `last_webhook_s` is still null after 15 minutes**, deliveries are not arriving or are being
     refused (for example a secret was not stored, which `create` would have said). The clock is
     already covering for them. Run `monitors.py delete` so the monitors stop costing credits, and the
     night continues on the clock.
10. **Monitor the night (optional):** run `scripts/budget.py status` now and then. Each Context.dev
    response also reports the balance (`key_metadata.credits_remaining`).

**To stop everything at once:** run `uv run python scripts/budget.py off`. All paid work is refused at
once, and the monitors pause themselves on their next delivery. Run `monitors.py pause` to pause them
immediately. To also unschedule the clock, redeploy with `MEMEPEDIA_CLOCK` unset. The site keeps
serving throughout.

**To fall back to the clock on purpose:** run `monitors.py pause` (or `delete`). Within 20 minutes the
already-scheduled clock notices the missing heartbeat and starts ticking. If monitor creation failed in
step 8, there is nothing to do: the clock never stopped.

## Morning checklist

1. `scripts/budget.py status`: check spend against the caps, whether the kill switch is off, and when the
   last webhook arrived. If background work stopped because a cap was reached and you want the wall live
   during the demo, raise the cap (`budget.py cap contextdev 5000`, `budget.py cap gemini 7000`) and run
   `monitors.py resume`: the guard paused them.
2. `curl <URL>/api/health`: compare the sighting count with 425 (before the night) plus whatever the
   backfill added.
3. Look at the site: the wall (SFW mode), "Rising today", "New specimens". Review any specimen the night
   created (`/api/week`) and delete or demote junk before the demo (see STATUS, "State of the data", for
   how earlier junk was handled).
4. Spot-check NSFW: the wall shows only `nsfw=false`, and the toggle reveals the rest.
5. Make sure the kill switch is **off** before the demo. Traces and identify depend on it.
6. Decide whether the monitors keep running through the demo (a live wall is the point) or pause.
7. After the hackathon: run `monitors.py delete`, then redeploy with `MEMEPEDIA_CLOCK` unset.

## Unknowns and risks

- The webhook payload fields (`data.run.monitor_id`, `credits_charged`, `status`, `data.change`) come
  from the docs and from the spike's run objects. They have not been seen in a live delivery. If the
  monitor id is missing, the delivery gets a 401 and the clock covers for it.
- Whether the create response includes `webhook.secret` ("visible only with full access"). The rotate
  endpoint is the fallback, and `create` says which happened.
- Reddit monitors now watch `/new/.rss`: the www page was blocked in the spike, the RSS feed was not.
  If a monitor fails 3 runs before its baseline, Context.dev pauses it, and it costs nothing more.
- A page monitor with relative timestamps ("5 minutes ago") will find a "change" on nearly every run.
  That is fine: each feed is then ticked about every 10 minutes, as estimated.
- Monitor secrets are stored in plain text in `webhook_monitors`. Anyone who can read the database can
  already do far more than trigger a capped tick.
- Background traces can add junk specimens overnight. They are capped at 10 per 24 hours, and step 3 of
  the morning checklist is the review.
