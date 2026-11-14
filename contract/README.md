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

## NSFW policy

`nsfw: boolean | null` lives on `MemeNode` and `Sighting` (`null` = not yet labelled). The archive
is shown to judges on a big screen, so the bar is deliberately stricter than a normal content
filter. NSFW means: nudity or sexual content/innuendo-heavy imagery; gore or graphic injury;
violence against real people; slurs or hate symbols; drugs depicted favourably; graphic bodily
fluids; or anything a reasonable person wouldn't show at a work presentation. Ordinary mild
swearing and dark-but-not-graphic humour are SFW. (The single source of truth for this definition
is the vision prompt in `backend/memepedia/llm.py`; this paragraph mirrors it.)

- **Sightings**: by default the backend never returns a sighting anywhere (`/api/wall`, the week
  view, SSE live events, `/api/tree/{id}`) unless its `nsfw` is exactly `false` — `true` and `null`
  (not yet labelled) are both excluded. `GET /api/wall` and `GET /api/tree/{id}` additionally take
  `sensitive=true`, which drops that filter and returns every sighting (including `nsfw: true` and
  `null`; on the tree, the selected meme's sightings); the default (`sensitive` unset or `false`)
  is unchanged. The frontend defensively hides any sighting with
  `nsfw !== false` that slips through anyway, unless the viewer has the sensitive toggle on.
- **Nodes** are never removed (that would break family trees). The frontend blurs a node's image
  with a click-to-reveal overlay whenever `nsfw` is `true` or `null`, and only shows it plainly
  once a human or the backfill has set it `false`. A header-level SFW/NSFW toggle
  (default SFW, persisted in `localStorage`) lets a viewer un-blur node images globally and,
  on the wall and in a meme's Sightings tab, also requests and shows nsfw sightings; it does not
  affect the other endpoints' filtering above.

## Changing the contract

Say so in the team chat first, then change `types.ts` and the affected fixture in the same commit.
