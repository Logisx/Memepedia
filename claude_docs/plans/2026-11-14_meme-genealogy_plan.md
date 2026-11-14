# Meme Genealogy — hackathon plan (Junction 2026)

Status: draft v2, 2026-11-14. About 20 build hours left, team of two, built mostly with Claude.

Changes in v2: Know Your Meme is no longer scraped (its terms forbid it); the archive is built from open sources and cited web evidence. Positioning is an open cultural archive, not an ad-funded site. Added the "this week in memes" strip, wiki-style edit affordances and a name shortlist.

## 1. Positioning

- **Main challenge:** Context.dev, "The Web Is Your Real-Time Database".
- **One-line pitch:** The open family tree of internet culture. Every meme, where it came from and what it is turning into, with a citation on every link, updated live.
- **Model:** a commons, like Wikipedia. Open-source code, open data, free API for researchers. An agent is the first editor; people verify, correct and dispute.
- **Who needs it** (for the "real-world impact" 20%):
  - Researchers and journalists tracing how a meme, including a harmful one, emerged and mutated. No structured, citable lineage dataset exists today.
  - Cultural conservation. Memes are the folk art of this era and their provenance disappears as platforms delete, lock down or die.
  - Brand and trust-and-safety teams who need to know whether a format is alive, dead or has grown a toxic branch.
- **How it pays for itself** (one slide, in case judges ask): the Wikimedia Enterprise pattern. The archive and a rate-limited API stay free; companies pay for high-volume API access and alerts ("a format your brand uses just changed meaning"). Grants and donations for digital heritage cover the rest. No advertising: ads next to third-party meme images are a legal and trust problem and contradict the commons framing.
- **Theme:** a natural-history museum of the internet. Memes are specimens with a first-recorded date, a mock-Latin name and a provenance card. The live feed is the curator's field log.
- **Name:** `memepedia` is registered on .com, .org, .wiki and .app. Unregistered when checked (confirm at a registrar): `memealogy.org`, `memealogy.com`, `originofmemes.org`, `originofmemes.com`, `memegenealogy.org`, `memelineage.com`, `memeancestry.com`, `memeroots.org`. Suggested: **Memealogy** on `memealogy.org` (.org suits a commons). About 10 euros and 10 minutes to attach to Vercel; do it in P3.

## 2. What the research established

| Question | Finding |
|---|---|
| Does a meme family-tree site already exist? | No interactive one was found. The niche looks open. |
| Can Know Your Meme be the source? | No. Its terms (Literally Media) forbid automated access and say "You may not aggregate the Content on your website or application". It is technically fetchable, but building on it contradicts the open-archive pitch and is a bad answer if a judge asks. KYM appears only as an outbound link when a search surfaces it. |
| What open sources exist? | Wikidata (CC0): 1,066 meme items, 494 with an English Wikipedia article, 77 with a "based on" link. Wikipedia text is CC BY-SA and describes origins and variants in prose with references. This is the backbone. |
| Where does the rest of the lineage come from? | The open web: explainer and news articles found through Context.dev search, read through Context.dev scrape, with each lineage claim stored alongside the quoted sentence and URL that supports it. |
| Reddit? | Direct access is closed (403 without auth, API signup closed). Whether Exa's index carries dated Reddit posts is unconfirmed; ask the Exa booth and spend at most 15 minutes testing. It is enrichment, not on the critical path. |
| Context.dev structured extraction | `POST /v1/web/scrape` with `formats: {json: true}` and `jsonParams: {schema, instructions}` returns typed JSON from any URL. |
| Context.dev research answers | `POST /v1/web/answers` takes a question and an example JSON shape, reads several pages and returns the filled shape plus the sources it read. Fast mode: 10 credits, 30 s budget. |
| Context.dev monitors | Targets: page, sitemap, extract, search query. Minimum interval 10 minutes. `POST /v1/monitors/{id}/run` triggers a run on demand. Webhook events `change.detected` and `run.completed`; exact payload still to be captured. |
| Credits | 50,000 with code JUNCTION26. Scrape 1, plus 1 to 4 for JSON extraction; search 1 per 10 results; answers 10; search monitor run 2. Expected total use: under 10,000. |

## 3. Data strategy: claims with evidence

Every edge in the tree is a **claim**: "B derives from A", with a relation type, a quoted sentence, a source URL and a date. A claim backed by two or more independent sources is shown as verified; one source is shown as unverified; none is not shown. This is what makes the archive honest without a curated source, and it is the Wikipedia rule of "citation needed" applied by an agent.

- **Backbone:** one SPARQL query to Wikidata for all meme items with inception dates, "based on" links and Wikipedia article URLs.
- **Flagship families:** about 10 archetypes (Wojak, Pepe, Doge, Rage Comics, Advice Animals, Trollface, Drake format, Distracted Boyfriend and object labeling, Loss, NPC). For each, draft a member list with an LLM, then run every member through the pipeline. Members whose lineage claim finds no citation are dropped.
- **Per-meme research:** `research(name)` gets first-seen date, origin, derived-from claims and variants, each with source and quote. Two candidate implementations, both on Context.dev; P0 decides which is primary:
  1. `/web/answers` in fast mode with a lineage-shaped example JSON (one call, sources included).
  2. `/web/search` for the top sources, then `/web/scrape` with a JSON schema on Wikipedia and two or three articles, then a merge step.
- **Images:** the hardest part now that KYM is out. Order of preference: Wikipedia lead image, the `og:image` or classified images from the best source page (Context.dev scrape `images` format), Imgflip's public template list. Display through Cloudinary fetch URLs with a credit link. A node with no image renders as a typeset specimen card, which still looks deliberate.

## 4. Scope ladder

One pipeline, three triggers: the seed script, the live monitors and a visitor's search all call `ingest(name)`, which researches a meme, stores it and walks its ancestors until it reaches a root or a meme already in the archive.

| Rung | Hours | What exists at the end |
|---|---|---|
| P0 Spikes and skeleton | 0 to 2 | Keys redeemed. Both research approaches tried on 5 memes and one chosen. Image sourcing tried on 10 memes. One search monitor created and its webhook payload captured. Next.js app with database deployed. Data contract agreed. |
| P1 Core | 2 to 9 | Archive of 150 to 250 memes across about 10 families, each edge with evidence. Genealogy view: time-axis tree, path to root highlighted, detail drawer with dates, quoted evidence and sources. Plain landing page with grid, search and random. |
| P2 Live | 9 to 14 | Monitors and news search feed new memes into the pipeline. "This week in memes" strip on the home page. Field-log ticker, "watching N sources" indicator, node-birth animation, "scan now" button. Searching a meme not in the archive traces it live with a streamed log. |
| P3 Delight and commons | 14 to 17 | Physics "meme pit" landing. Time scrubber. Museum styling. Wiki affordances on every node: Edit, Dispute this link, Add a source, History (History is real: it lists the agent's own changes from the events table; the others open a "coming soon" panel). Open-data page with API description and licence. Domain attached. |
| P4 Stretch | if time | "Add a source" working for real: paste a URL, the pipeline scrapes it, extracts the claim and files it as a pending proposal. Paste your own meme (vision model identifies it, then traces it). Reddit earliest sightings through Exa if the booth confirms it. |
| Wrap-up | last 3 | Feature freeze, backup video, rehearsal, submission notes for side challenges. |

## 5. Architecture

**Stack:** one Next.js (App Router) app in TypeScript on Vercel, Postgres on Aiven. Libraries: `context.dev` SDK, `@xyflow/react` for the tree, `motion` for animation, `matter-js` for the pit, Tailwind, `postgres` for SQL.

```
 seed script ─────┐
 monitors + news ─┼─► ingest(name) ─► research(name) via Context.dev ─► upsert meme
 visitor search ──┘        │                                            write claims (edges)
                           └─ parent not in archive? ingest(parent)     write events
                                                                             │
   landing / tree / strip / ticker ◄── GET routes, polled every 4 s ◄────────┘
```

**Data model (3 tables)**

- `memes`: `id` (slug), `name`, `latin_name`, `image_url`, `image_credit_url`, `first_seen` (date), `date_precision`, `origin_platform`, `summary`, `status` (verified, unverified), `wikidata_id`, `sources` (jsonb list of `{url, title, date, kind}`), `ingested_at`.
- `edges`: `child_id`, `parent_id`, `relation` (variant, remix, crossover, format), `evidence` (jsonb list of `{quote, url, date}`), `status` (verified, unverified, disputed).
- `events`: `id`, `ts`, `type` (scan, detected, traced, linked, news), `meme_id`, `message`, `source_url`.

**API contract (freeze at hour 2)**

- `GET /api/memes?q=` list for landing and search
- `GET /api/tree/[id]` every node and edge in the family that contains `id`
- `GET /api/events?since=` ticker and new-node feed
- `GET /api/news` items for the "this week in memes" strip
- `POST /api/trace` body `{query}`; streams progress lines, ends with a meme id
- `POST /api/webhooks/context` monitor webhook receiver
- `POST /api/scan` triggers the monitor runs on demand

**Context.dev endpoints and what each drives**

| Endpoint | Use |
|---|---|
| `/web/answers` (fast) or `/web/search` plus `/web/scrape` with `json` | `research(name)`: dates, origin, derived-from claims with quotes and sources |
| `/web/scrape` with `images` | Image for a node |
| `/news/search` (last 7 days) | "This week in memes" strip, and candidates for new memes |
| `/monitors` with a search target, every 10 minutes, plus webhook | New-meme detection from the open web |
| `/monitors` with sitemap or page targets on a few culture-news meme sections | Second live signal |
| `/web/scrape` with `json` on a submitted URL | "Add a source" proposals, P4 |

**Live flow:** a monitor or news result arrives, the article is scraped with a schema asking "which memes does this describe, what does each derive from", each named meme goes through `ingest(name)`, and the result is linked into its family as unverified until a second source agrees.

**Genealogy view:** horizontal time axis (x is first-seen date, y is branch lane) in React Flow with custom image nodes. Layout: y from `d3-hierarchy` on each node's primary parent, x from a time scale snapped to months; a second parent is an extra curved edge. Verified edges are solid, unverified dashed. More than 8 children collapse into a "+N descendants" bundle. Fallback if the custom layout is not working by hour 6: dagre left-to-right in the same canvas.

## 6. Split

| | Person A (AI and backend): data and agents | Person B (backend and frontend): experience |
|---|---|---|
| P0 | Redeem Context.dev credits; try both research approaches and image sourcing; create a monitor and capture the webhook payload | Scaffold Next.js, create Aiven Postgres, deploy to Vercel, write a hand-made fixture family (about 15 Wojak nodes) |
| P1 | `lib/context.ts`, `lib/research.ts`, `lib/ingest.ts` with ancestor walk, Wikidata backbone query, `scripts/seed.ts`, run the seed | Read routes, time-axis tree, focus path, detail drawer with evidence, plain landing with search and random |
| P2 | Webhook route, `/api/scan`, `/api/trace` streaming, news ingestion, event writing | "This week" strip, ticker, source indicator, node-birth animation, trace progress UI |
| P3 | Open-data page content, verification status logic, domain | Meme pit, time scrubber, museum styling, wiki affordances and History tab |
| P4 | "Add a source" pipeline, vision identification, Exa test | Proposal UI, paste and drop zone |

Sync points: hour 2 (contract frozen, skeleton deployed), hour 9 (real data in the real tree), hour 14 (a new meme travels end to end), hour 17 (feature freeze).

## 7. Demo (3 minutes)

1. **Hook, 15 s.** "Memes are the folk art of our time, and nobody is keeping the family records." Landing page with this week's strip on screen.
2. **A known family, 45 s.** Pick Doomer. The tree opens with the path back to Wojak highlighted. Drag the time scrubber and the family grows. Open a node: first-recorded date, the quoted sentence that supports the parent link, sources, and the Edit, Dispute and History tabs.
3. **Judge's choice, 60 s.** Ask a judge to name a meme. The trace runs live: the log shows each Context.dev call and the tree assembles ancestor by ancestor.
4. **Live, 40 s.** Point at "watching N sources, last scan 3 min ago". Press scan now. A meme from this week's news is detected, appears in the field log and is born into its family as an unverified specimen.
5. **Close, 20 s.** Open source, open data, free for researchers; the commercial API and alerts fund it. Which Context.dev endpoints power it.

To make step 4 reliable without faking it: do not ingest the most recent 48 hours of news before the demo, so a real scan always finds memes new to the archive. Record a backup video at feature freeze.

## 8. Accounts, keys and who to ask

| What | How | Needed by |
|---|---|---|
| Context.dev | Sign up at context.dev/signup, redeem `JUNCTION26` at context.dev/dashboard/redeem-credits | Hour 0 |
| Vercel and a GitHub repo (public, with a licence file) | Self-serve, free tier | Hour 0 |
| Aiven Postgres | Self-serve free plan; ask the Aiven booth for hackathon credits | Hour 1 |
| Cloudinary | Self-serve free account; only the cloud name is needed for fetch URLs | Hour 3 |
| LLM key for the merge step and member lists (Gemini from aistudio.google.com is free and self-serve) | Self-serve | Hour 2 |
| Domain | Any registrar, about 10 euros | Hour 14 |
| Exa | Code `EXA50JUNCTION` at dashboard.exa.ai/billing, only if the Reddit test goes ahead | P4 |

Questions for the Context.dev mentors in the first hour: the exact `change.detected` payload for search monitors; whether `/web/answers` can exclude a domain; concurrency on the hackathon plan; the pattern they recommend for "new items across several news sources".
Question for the Exa booth: does the index return dated Reddit posts and comments with text for a domain-filtered query?

## 9. Risks and fallbacks

| Risk | Fallback |
|---|---|
| Lineage from open sources is thinner or noisier than a curated encyclopedia | Seed from flagship families with drafted member lists; require evidence per edge; show verification status so thin data reads as honesty, not as a bug |
| No good image for many memes | Typeset specimen cards; prioritise families with strong imagery for the demo |
| `/web/answers` is slow or shallow | Search plus scrape-with-schema plus merge, which is slower to build but controllable |
| Open-web monitors surface noise, not new memes | The extraction step asks "is this a distinct, named meme" and discards the rest; the strip can still show the news item |
| Custom time-axis layout eats too many hours | Switch to dagre left-to-right at hour 6 |
| Trace takes longer than a serverless request allows | Stream progress, cap the ancestor walk at depth 5, run webhook ingestion as a background task |
| Third-party images and text | Thumbnails with credit links, quotes limited to one sentence with source; Wikipedia-derived text keeps its CC BY-SA attribution |

## 10. Side challenges

| Challenge | Cost to enter | Verdict |
|---|---|---|
| Context.dev "Best Use" | None, same repo plus a note on endpoints | Enter |
| Aiven | Use Aiven Postgres as the database | Enter |
| Cloudinary | Fetch-URL image delivery plus one of their four listed tools and their survey form | Enter if the tool takes under 30 minutes |
| Gemini API | Already used if Gemini does the merge step; stronger if P4 vision ships | Enter |
| NVIDIA Nemotron | Could do P4 vision (OpenAI-compatible API) | Only if P4 is reached with time to spare |
| Oxylabs | Needs a second scraping provider at runtime | Skip |
| Modal, Gemma, Hostinger | No natural fit | Skip |
| Exa (main challenge) | Different brief (personal task agent) | Skip as a submission; possibly use the API for Reddit |
