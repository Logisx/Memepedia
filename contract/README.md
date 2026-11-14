# Contract between the two halves

Memepedia is built as two independent halves that meet only here.

| Half | Folder | Branch | Stack | Needs from the other half |
|---|---|---|---|---|
| Data and agents | `backend/` | `pipeline` | Python, FastAPI, Postgres | Nothing |
| Experience | `web/` | `web` | React, TypeScript, Vite | Nothing; runs on the fixtures in this folder |

- `types.ts` is the single source of truth for every JSON shape. The backend's Pydantic models mirror it.
- `fixtures/` holds one JSON file per endpoint, shaped exactly as the backend will respond. The frontend runs entirely on these until the merge.
- Merging means setting one environment variable in the frontend (`VITE_API_BASE`) so it calls the real backend instead of reading fixtures.

## Endpoints

| Method and path | Returns | Fixture |
|---|---|---|
| `GET /api/wall?since=<iso>&limit=60` | `WallResponse` | `wall.json` |
| `GET /api/nodes?q=<text>&limit=20` | `NodesResponse` | `nodes.json` |
| `GET /api/nodes/random` | `RandomResponse` | pick from `nodes.json` |
| `GET /api/tree/{id}` | `TreeResponse` | `tree-<id>.json` |
| `GET /api/related?a=<id>&b=<id>` | `RelatedResponse` | `related-<a>-<b>.json` |
| `GET /api/week` | `WeekResponse` | `week.json` |
| `POST /api/trace` body `{query}` | server-sent events of `TraceEvent` | `trace-sample.json` (array of `{delay_ms, event}`) |
| `POST /api/identify` multipart `image` | `IdentifyResponse` | `identify.json` |
| `POST /api/proposals` body `{node_id, url, note}` | `ProposalResponse` | `proposal.json` |

## Rules both halves follow

- Dates are ISO strings in UTC. `first_seen` is a date; `posted_at` and `ts` are datetimes.
- A missing image is `null`, never an empty string. The UI draws a typeset specimen card when there is no image.
- The wall is polled: the frontend calls `/api/wall` with the `server_time` of the previous response as `since`, every 5 seconds.
- An inferred link has `quote`, `source_url` and `source_title` all `null`.
- Errors are `{ "error": "<message>" }` with a 4xx or 5xx status.
- The backend allows cross-origin requests from any origin during the hackathon.

## Changing the contract

Say so in the team chat first, then change `types.ts` and the affected fixture in the same commit.
