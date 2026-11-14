# Merge try-outs: frontend against the deployed backend

Run 2026-11-14 from the `web` branch. Backend: `https://aleksandr-shishkov-work--memepedia-web.us-east.modal.run`, set as `VITE_API_BASE` in `web/.env.local` (git-ignored). The frontend ran on its dev server and was driven through headless Chrome, so each call went through the real `web/src/data.ts` code path.

The driver script lives in the session scratchpad, not in the repo. It is a plain Node script that talks to Chrome over the DevTools protocol; ask for it to be added to `web/` if it should be kept.

## Summary

| Area | Result |
|---|---|
| Response shapes of the 8 GET endpoints | Match the fixtures; no contract mismatch |
| Cross-origin calls, 404 error shape | Work as the contract says |
| Click-through on real data (13 checks) | 12 pass; the 13th was a test false positive (see below) |
| `POST /api/trace` with an unknown meme | **Failed** after about 40 s: "Something went wrong while tracing this meme." |
| `POST /api/identify` with a real Doomer image | Worked: opened `/meme/doomer` in 5.6 s |
| `POST /api/proposals` with a Wikipedia URL | **Rejected**: "Could not read that page." after 1.0 s |

Two of the three paid calls failed on the backend side. The frontend handled both correctly (error shown, retry offered); the cause is in the backend or its deployment and is not yet known.

## 1. Read endpoints

`/api/wall`, `/api/nodes`, `/api/tree/{id}` (doomer, swole-doge-vs-cheems, wojak), `/api/related` (both fixture pairs) and `/api/week` were fetched and compared key by key and type by type against the matching fixture. No differences. `/api/health` reported 35 nodes, 23 links, 87 sightings, 14 history rows.

Latency over three rounds: `/api/nodes` about 0.8 s, `/api/wall` 1.1 to 1.3 s, `/api/week` 1.3 to 1.5 s, `/api/tree/doomer` 2.4 to 2.6 s.

Other API behaviour checked by hand:
- A preflight and a GET with an `Origin` header both return `Access-Control-Allow-Origin: *`.
- `/api/tree/no-such-meme` returns 404 with `{"error":"Unknown node."}`.
- `POST /api/trace` with `{"query":"Doomer"}` (a meme already in the archive) streams `data: {...}` events and ends with the chain already cited. The frontend then opens `/meme/doomer`.

## 2. Click-through on real data

Thirteen checks (wall, week strip, search suggestions, lineage for four memes, unknown id, trace of a known meme, related). Twelve pass. The failing check was "week strip rendered", which also fails whenever any tile on the wall shows the text "image unavailable". One live Imgflip post, `i.imgflip.com/b5vd7b.jpg`, now returns 404, so a tile showed that text. The app behaved as designed; the check was wrong.

## 3. Paid calls, once each

Each was run once, through the app.

### 3.1 Trace of an unknown meme: failed

- **Input:** query `Rickroll` at `/trace?q=Rickroll`.
- **Field log as shown:**
  - `[00:01.9] Searching the archive…`
  - `[00:02.3] Hypothesising a lineage…`
  - `[00:41.5] Trace failed: Something went wrong while tracing this meme.`
- **Observed:** no `chain` event arrived (0 chain cards). The error came 39 seconds after "Hypothesising a lineage…". The screen showed the error and a "Try again" button.
- **What the backend code says:** that message is the catch-all in `backend/memepedia/trace.py` (`except Exception` around the whole trace, logged server-side as `trace failed for query …`). The response does not say which step failed.
- **Not verified:** the cause. The 39 s gap suggests a slow or timed-out call during the hypothesise step, either the Context.dev search for an unknown meme or the Gemini draft. The server log on Modal would show it.

### 3.2 Identify a dropped image: worked

- **Input:** the Imgflip Doomer image (`i.imgflip.com/4/37i3fq.jpg`, 7.8 KB).
- **Result:** the app opened `/meme/doomer` after 5.6 s.
- **Not covered:** the unknown-image branch (a `trace_query` handed to the trace), since this image was a known meme.

### 3.3 Suggest a source: rejected

- **Input:** on `/meme/thirty-year-old-boomer` (its link to Wojak is inferred in the real database), URL `https://en.wikipedia.org/wiki/Wojak`, note "Wojak variants include the boomer".
- **Result:** "Not accepted. Could not read that page." after 1.0 s.
- **What the backend code says:** "Could not read that page." is the message for a `ContextDevError` in `propose()` in `trace.py`. A page read of a normal Wikipedia article taking 1 s and failing points at the Context.dev call itself (key, credits, rate limit or a blocked fetch), not at the page.
- **Not verified:** the cause, and whether a proposal row was written to `history`.

### Likely common cause (unconfirmed)

Both failures involve Context.dev, and identify, which uses Gemini only, worked. So Context.dev may not be working in the deployed environment. Things to check on the backend side:
1. The Modal secret carries the Context.dev key under the name the code reads. `backend/deploy.py` lists `CONTEXTDOTDEV_KEY` as required, while some notes call it `CONTEXTDEV_KEY`.
2. Context.dev credits and any rate limit on the key.
3. The Modal server log for the two requests.

## 4. Other observations

- **Image failures:** besides the Imgflip URL above, two Reddit images (`i.redd.it/we2bj88tqj1i1.jpeg`, `i.redd.it/g1soaa87li1i1.jpeg`) return 404 in the browser. The wall shows "image unavailable" for them.
- **Archive size:** the deployed database still looks like the mock archive (35 nodes), not the 62-meme curated seed. Pepe's lineage shows a single card and a single map node.
- **Wall timestamps:** the mock sightings are hours old, so the wall reads "spotted 30 min ago" and older, not "just now".
- **Credits:** the three paid calls spent a small amount of Context.dev and Gemini quota; the backend's ledger (`backend/.data/credits.jsonl`) has the exact figure.
