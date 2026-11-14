# Memepedia — hackathon plan (Junction 2026)

Status: draft v3.1, 2026-11-14. This is the product and logic reference; the two per-person plans next to it are the build order. About 19 build hours left, team of two, built mostly with Claude.

Changes in v3 (after live-source tests and a two-round adversarial review): the archive now tracks live posts from social sources as **sightings**; lineage is drafted by an LLM and then verified against the web, instead of being mined from prose; a vision model is core; the home screen is a live wall; the tree view is a descent strip plus a family map. Cut: time-axis layout, time scrubber, physics pit, news search, culture-news monitors.

## 1. Positioning

- **Main challenge:** Context.dev, "The Web Is Your Real-Time Database".
- **Pitch:** The open family tree of internet culture. Every meme posted right now has ancestors; we show them, with a citation on every link.
- **Model:** a commons like Wikipedia. Open-source code, open data, free API for researchers. An agent is the first editor; people verify and correct.
- **Who needs it:** researchers and journalists tracing how a meme emerged and mutated; cultural conservation as platforms lock down or delete; brand and trust-and-safety teams who need to know whether a format is alive, dead or has grown a toxic branch.
- **Sustainability (one slide if asked):** the Wikimedia Enterprise pattern. Archive and rate-limited API stay free; companies pay for high-volume access and alerts. Grants for digital heritage. No advertising.
- **Theme:** a natural-history museum of the internet: specimens, first-recorded dates, mock-Latin names, provenance cards.
- **Name and domain:** `memepedia.fi` is unregistered (Traficom whois: "Domain not found"). Register it through any accredited .fi registrar when one of you has ten spare minutes.

## 2. Facts the design rests on

| Topic | Finding |
|---|---|
| Know Your Meme | Terms forbid automated access and aggregation. Not scraped; outbound links only. |
| Open backbone | Wikidata: 1,066 meme items, 77 "based on" links. Too sparse to mine lineage from; useful for dates and identity. |
| Live social sources, plain curl | Lemmy JSON API works (titles, timestamps, image URLs, scores, `sort=TopWeek`). Imgflip hot page works but is partly JS-rendered. trends24.in (X trends) and Mastodon trends respond. Reddit RSS and old.reddit answered once, then 429. Reddit JSON, Bluesky public search, 9GAG, Memedroid return 403. |
| Reddit | Only reachable through a provider with proxies. To be tested through Context.dev scrape in P0. Exa's Reddit coverage is unconfirmed and can only be checked with a key. |
| Context.dev | Scrape with JSON-schema extraction on any URL; search; research answers; monitors on page, sitemap, extract or search targets with a 10-minute minimum interval and on-demand runs; webhooks `change.detected` and `run.completed`. Costs: scrape 1 credit plus 1 to 4 for extraction, search 1 per 10 results, page-monitor run 1, extract-monitor run 10. Budget 50,000. |
| Hosting | The backend needs a public URL for Context.dev webhooks and for judges. Modal (a Junction sponsor) provides that plus scheduled functions; Context.dev monitors remain the primary clock. |

## 3. The logic

**What a node is.** A node is a meme *format*: a character (Wojak), a template (Distracted Boyfriend) or a phrase. A single post is never a node; it is a **sighting** attached to a node.

**Two lines of descent.** A meme can have one parent on each axis:
- character line: who it is about (Swole Doge descends from Doge);
- format line: how it is built (Swole Doge vs Cheems uses the Virgin vs Chad format).

A family is everything connected on the character line. Format links are shown only for the selected meme, as a chip that jumps to that format's family.

**No empty trees.** Every node ends at one of about 10 format-class roots (image macro, object labelling, reaction image, drawn character, comparison, copypasta and so on).

**Identity.** Each node has aliases. The resolver takes a name, pulls the 10 closest existing names and aliases, and asks the LLM "same as one of these, or new?". Without this, "Doomer", "Doomer Wojak" and "Wojak (Doomer)" become three nodes.

**Lineage: hypothesise, then verify.**
1. The LLM drafts the chain from the meme to a root, choosing parents from archive candidates. For a meme the resolver does not know, a Context.dev search on its catchphrase or overlaid text supplies context first.
2. Each link is verified in parallel: Context.dev search for both names, scrape the top pages, find a sentence that mentions both. The quote must be a verbatim substring of the scraped page.
3. A link with a quote is **cited**. A link without one is **inferred** and drawn dashed with "citation needed".
4. Invariants: a parent is not younger than its child; no cycles; quotes pass the substring check.

**Sightings.** Each new post goes through one vision call that returns structure, not prose: `{template_guess, confidence, structure_class, subjects, overlaid_text, catchphrase}`. The resolver attaches it to a node or leaves it pending.

**Emerging memes.** Each tick, one LLM call groups pending sightings from the last 72 hours. A group becomes a new **specimen** only if it has at least 3 sightings from at least 2 authors that share an image or structure but differ in overlaid text (identical text is a repost; for phrases the test inverts). The specimen is re-checked against the resolver, placed under its structure-class root and traced. Specimens with no new sightings for 7 days expire.

## 4. Architecture

**Stack:** two independent halves that meet at `contract/`. Backend: Python (uv, FastAPI) on Modal, Postgres on Aiven, Gemini Flash for vision and text, Context.dev over HTTP. Frontend: a static React app (Vite, TypeScript, Tailwind, `@xyflow/react` with dagre, `motion`) that runs on fixtures until the merge. Build order for each half: `2026-11-14_backend-pipeline_plan.md` and `2026-11-14_frontend-experience_plan.md`.

```
 SOURCES                      PIPELINE (server)                      STORE          SCREENS
 ───────                      ─────────────────                      ─────          ───────
 Lemmy API ──────────┐
 Reddit*, Imgflip hot,│      ┌──────────────────────────────┐
 X trends ────────────┼─────►│ LIVE LOOP                    │──► sightings ──►  Wall (home)
   (*via Context.dev  │      │ fetch → look → resolve       │                   This week
    scrape)           │      └──────────────┬───────────────┘
                      │                     │ unknown, 3+ alike
 Context.dev page ────┘ tick                ▼
 monitors (scheduler)        ┌──────────────────────────────┐
                             │ TRACE                        │──► nodes, links ─► Lineage
 visitor: search, ──────────►│ resolve → hypothesise →      │                    Related
 dropped image               │ verify on the live web       │──► history ─────► History tab
                             └──────────────┬───────────────┘
 Context.dev search ◄───────────────────────┘
 and scrape (evidence)
```

**The live loop** (runs by itself; a monitor fires every few minutes)

```
 Context.dev page monitor fires ─► POST /api/webhooks/context
                                          │
                              1  FETCH    new posts from that source
                                          │   post = image + title + author + time + link
                              2  LOOK     Gemini vision: which template, what text
                                          │   (max 10 images per tick, in parallel)
                              3  RESOLVE  match against node names and aliases
                                   ┌──────┴───────┐
                               match           no match
                                   │              │
                         save SIGHTING       hold as PENDING
                         on that node        3+ alike from 2+ authors?
                                   │              │ yes
                                   ▼              ▼
                         wall shows it      new SPECIMEN ─► TRACE
                         "spotted 6 min ago · family: Wojak"
```

**The trace** (on demand: a search, a dropped image, or a new specimen)

```
 name or image ─► RESOLVE ─► already in archive? ── yes ─► open its lineage
                                  │ no
                     A  HYPOTHESISE   LLM drafts the chain to a root
                                  │   (unknown meme: Context.dev search first)
                                  │   screen shows the chain dashed within seconds
                     B  VERIFY        per link, in parallel:
                                  │   Context.dev search → scrape → sentence naming both
                          ┌───────┴────────┐
                     quote found       none found
                          │                │
                     link CITED       link INFERRED
                     (turns solid)    (stays dashed, "citation needed")
```

**Data model (4 tables)**

- `nodes`: `id`, `name`, `aliases` (text[]), `kind` (character, template, phrase, format_class), `latin_name`, `image_url`, `image_credit_url`, `first_seen`, `date_precision`, `summary`, `status` (established, specimen), `created_at`.
- `links`: `child_id`, `parent_id`, `axis` (character, format), `status` (cited, inferred), `quote`, `source_url`, `created_at`.
- `sightings`: `id`, `platform`, `post_url` (unique), `image_url`, `title`, `author`, `posted_at`, `vision` (jsonb), `node_id` (nullable), `state` (resolved, pending, unclassified), `cluster_id`.
- `history`: `id`, `ts`, `type` (traced, cited, specimen, proposal), `node_id`, `message`, `source_url`, `payload` (jsonb). Proposals from visitors live here with a pending flag.

**API contract (freeze at hour 2)**

- `GET /api/wall?since=` sightings with their node stamp
- `GET /api/nodes?q=` search
- `GET /api/tree/[id]` character-line family, both descent chains, the selected node's format links
- `GET /api/related?a=&b=` common ancestor per axis
- `GET /api/week` rising families and new specimens
- `POST /api/trace` body `{query}`; streams the dashed chain, then link updates
- `POST /api/identify` image upload; returns a node id or starts a trace
- `POST /api/webhooks/context` monitor tick
- `POST /api/proposals` URL plus note; runs the verifier on the URL

**Context.dev, and what each call drives**

| Call | Drives |
|---|---|
| Page monitors plus `run.completed` webhook, staggered | The live loop's clock |
| `/web/scrape` on Reddit, Imgflip hot, trend pages | Sightings from sources a plain client cannot read |
| One extract monitor on a trends page | Trend text as a second signal |
| `/web/search` then `/web/scrape` | Evidence quote for every cited link; context for unknown memes |
| `/web/scrape` on a visitor's URL | "Suggest a source" |

## 5. Screens

- **Wall (home).** Masonry of live sightings, each stamped "spotted N min ago on <platform> · family: <name>". New ones arrive one at a time. Search box, drop-an-image zone, random button. "This week in memes" strip above: families rising (last 24 hours against the prior six-day mean) and specimens identified this week, computed from sightings including the Lemmy week backfill.
- **Lineage.** Top 45%: the line of descent as 4 to 6 large cards, oldest on the left, each with image, year, Latin name and the quote that links it to the next. Cards flip in back through time on open. Toggle between character line and format line. Bottom 55%: the whole family as a top-to-bottom map, children capped at 8 plus "+N", selected path highlighted, dashed for inferred links. Recent sightings of the selected meme along the side.
- **Related.** Pick two memes: "by character: both descend from Doge (2013); by format: both use Virgin vs Chad".
- **History tab** on every node: the agent's changes and pending proposals. "Suggest a source" takes a URL and a note; if the URL contains a qualifying sentence the link flips to cited.

## 6. Scope ladder

| Rung | Hours | What exists at the end |
|---|---|---|
| P0 Go/no-go and skeleton | 0 to 2 | Keys. App with database deployed. Four tests run (section 7). Contract frozen. |
| P1 Lineage | 2 to 8 | Resolver. Trace with hypothesise and verify. Seed: 10 format-class roots, 5 families of 60 to 80 nodes checked by hand, Imgflip top 100 templates. Lineage screen. Search. |
| P2 Live | 8 to 13 | Live loop with vision. Lemmy week backfill. Wall as home. Drop an image. "This week" strip. |
| P3 Depth | 13 to 16 | Emerging specimens. Related. Suggest a source and History. Museum styling and Latin names. Domain. |
| Wrap-up | 16 to 19 | Freeze. Hand-check the three demo families. Backup video. Rehearsal. Side-challenge notes. |

## 7. P0 tests and thresholds

| Test | Pass | If it fails |
|---|---|---|
| Vision labelling on 20 hand-labelled Lemmy posts | At least 70% of posts using a seeded template named correctly; at most 2 confident wrong names; at least 6 of 20 resolve to a node | Stamp families only on high-confidence matches, show the rest as unclassified, drop emerging detection |
| Social sources | At least 2 image sources with timestamps, one fetched through Context.dev, plus one trend-text source | Several Lemmy instances as separate sources; Context.dev stays as scheduler and verifier |
| Reddit through Context.dev (20 minutes): `old.reddit.com/r/memes/new` three times, five minutes apart | Each returns at least 20 posts with timestamps and image URLs | Drop Reddit; optionally give Exa 15 minutes |
| Verify step on 5 known links | A verbatim quote found for at least 3 | Loosen to "page about the child mentions the parent or an alias" |
| Monitor to webhook | Payload captured, serverless duration limit known | Laptop worker with a tunnel for the live loop |

## 8. Split

| | Person A (AI and backend) | Person B (backend and frontend) |
|---|---|---|
| P0 | Context.dev key, vision test, source tests, verify test | Scaffold, Aiven Postgres, deploy, monitor-to-webhook capture, fixture family |
| P1 | Resolver, trace, seed script, hand-check | Lineage screen (descent strip, family map), search, trace streaming UI |
| P2 | Live loop, vision, Lemmy backfill, `/api/week` | Wall, drip release, drop zone, strip |
| P3 | Emerging clustering, proposal verifier | Related, History tab, styling, domain |

Sync points: hour 2 (contract frozen, tests read out), hour 8 (real lineage on the real screen), hour 13 (a live post reaches the wall with its family), hour 16 (freeze).

## 9. Demo (3 minutes)

1. **Hook, 20 s.** The wall is already moving. "Each of these was posted in the last hour. Every one has ancestors."
2. **The moment, 50 s.** Click a sighting that is minutes old. The descent cards flip back through time. "This post is six minutes old. Its great-grandfather is from 2010." Show a cited link's quote and source, and one dashed "citation needed".
3. **Judge's choice, 50 s.** A judge names a meme or drops an image. The dashed chain appears in seconds and links turn solid as citations land.
4. **Depth, 30 s.** "This week" strip and an unidentified specimen the archive noticed before anyone named it. If time: two memes, how they are related.
5. **Close, 30 s.** Open commons, free for researchers, companies fund it. Context.dev is the clock, the eyes on closed sources and the fact-checker.

Pre-seeding the Imgflip top 100 makes most judge picks instant. The wall needs no button press; an on-demand monitor run is the backup. Record a backup video at freeze.

## 10. Accounts and keys

| What | How | Needed by |
|---|---|---|
| Context.dev | context.dev/signup, redeem `JUNCTION26` | Hour 0 |
| Gemini API key | aistudio.google.com, free | Hour 0 |
| Vercel and a public GitHub repo with a licence file | Self-serve | Hour 0 |
| Aiven Postgres | Free plan; ask the booth for credits | Hour 1 |
| Cloudinary | Free account; cloud name for fetch URLs | Hour 3 |
| `memepedia.fi` | Accredited .fi registrar | P3 |
| Exa | `EXA50JUNCTION`, only if the Reddit test fails and there is time | Optional |

## 11. Risks

| Risk | Response |
|---|---|
| The model's drafted lineage is wrong for a known meme | Hand-check the three demo families; invariants; "inferred" is shown honestly |
| Vision mislabels and the wall stamps wrong families | Confidence threshold; unclassified is better than wrong |
| Duplicate nodes | Resolver with aliases on every write path |
| Only Lemmy is reachable | The product still works; the pitch leans on verification and scheduling |
| Serverless time limits in the webhook | 10 images per tick, background continuation, laptop worker as fallback |
| Third-party images | Thumbnails with a credit link to the original post; no rehosting beyond a cache |

## 12. Side challenges

| Challenge | Verdict |
|---|---|
| Context.dev "Best Use" | Enter; same repo plus a note on endpoints |
| Aiven | Enter; Postgres is the database |
| Gemini API | Enter; vision and lineage drafting are core |
| Cloudinary | Enter only if their listed tool takes under 30 minutes; fetch URLs are used either way |
| Nemotron, Oxylabs, Modal, Gemma, Hostinger, Exa main challenge | Skip |
