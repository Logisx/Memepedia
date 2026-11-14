# Memepedia — current status

Last updated: 2026-11-14, about 15:45 EET. Read this first when picking the project up in a new session.

## In one paragraph

Memepedia is a hackathon project (Junction 2026, team of two, main challenge: Context.dev "The Web Is Your Real-Time Database"). It is a live meme genealogy site: posts seen on social feeds minutes ago are stamped with the meme family they belong to, and any meme can be traced back to its origin with a quoted source on every link. Planning and feasibility testing are done. **No product code has been written yet.** The owner asked that implementation not start until they say go.

## Where everything is

| What | Where |
|---|---|
| Product, logic, demo script, positioning | `claude_docs/plans/2026-11-14_meme-genealogy_plan.md` |
| Build order for the backend half (the repo owner) | `claude_docs/plans/2026-11-14_backend-pipeline_plan.md` |
| Build order for the frontend half (the teammate) | `claude_docs/plans/2026-11-14_frontend-experience_plan.md` |
| JSON shapes both halves agree on | `contract/types.ts`, `contract/README.md` |
| Mock data, one file per endpoint | `contract/fixtures/` (see its README; run `python3 -I contract/fixtures/check_fixtures.py` to validate) |
| Feasibility test scripts, samples and results | `spikes/`, results in `spikes/P0_RESULTS.md` |
| Secrets | `.env` (git-ignored): `CONTEXTDOTDEV_KEY`, `GEMINI_EMAIL`, `GEMINI_PASSWORD` |

## Done

- Research on data sources, the Context.dev API, visual form and side challenges.
- Two-round adversarial review of the plan; the design in the main plan is the outcome.
- The split into two independent halves, with a contract and mock data so neither waits on the other.
- Context.dev feasibility tests (about 55 of 50,000 credits used). Summary:
  - Reddit works through its RSS feeds read with Context.dev scrape; normal pages and the JSON endpoint are blocked, sometimes with an HTTP 200.
  - Imgflip is readable with `formats: {images: true, html: true}`; no timestamps, no clean template name.
  - The quote-verification step found a supporting sentence for 4 of 5 known links (3 to 21 s, 4 to 6 credits each).
  - Monitors work at a 10-minute interval and can act as the scheduler.
- Domain check: `memepedia.fi` was unregistered on 2026-11-14. Not bought.

## Not done

- The vision go/no-go test (needs a Gemini API key).
- Everything in steps B1 onward of the backend plan and F0 onward of the frontend plan.
- No accounts created yet for Modal or Aiven. Nothing is deployed.

## Decisions made

- Know Your Meme is not scraped (its terms forbid aggregation). Lineage is drafted by an LLM and verified against the open web through Context.dev.
- A node is a meme format; a single post is a sighting attached to a node.
- Two lines of descent per meme: character and format. Every meme ends at a format-class root.
- Links are "cited" (verbatim quote found) or "inferred" (shown dashed as "citation needed").
- Live sources, in build order: Lemmy (direct JSON API), Reddit RSS through Context.dev, Imgflip through Context.dev.
- Backend in Python (uv, FastAPI); frontend a static React app. The halves meet only at `contract/`.
- Positioning: an open cultural archive in the spirit of Wikipedia; no advertising.

## Decisions waiting on the owner

1. **Go-ahead to start building.**
2. **Gemini API key.** `.env` holds the temporary account's email and password. Log in at aistudio.google.com, open aistudio.google.com/api-keys, copy the key into `.env` as `GEMINI_API_KEY`. Never commit it; Google closes the account if the key reaches GitHub.
3. **Hosting and database.** Proposed: Modal for the backend and Aiven free Postgres. Each needs a free signup. Alternative for hosting: the laptop behind a tunnel.
4. **Code standards for the weekend.** The owner's global rules ask for strict mypy, tests first and functions under 20 lines. Proposed: keep typing, Ruff and short functions; tests for pure logic only; smoke scripts for anything calling an external service.
5. **How the teammate gets the code.** Everything is on the `pipeline` branch. Either the teammate branches `web` from `pipeline`, or `pipeline` is merged into `main` first.

## Next actions

For the backend session, in order:
1. Confirm the open decisions above with the owner.
2. Run the vision test on 20 hand-labelled Lemmy posts against the thresholds in section 5 of the backend plan.
3. Start step B1 of the backend plan.

For the teammate:
1. Fetch the `pipeline` branch, create `web` from it.
2. Give `claude_docs/plans/2026-11-14_frontend-experience_plan.md` to the coding assistant and start at step F0.

## Working agreements

- `main` is protected: no commits, merges or pushes to it without the owner's explicit confirmation. Work happens on `pipeline` (backend) and `web` (frontend).
- Commit regularly, with small commits.
- The main session decides; subagents do the legwork: Opus for outsourced thinking, Sonnet for implementation, Haiku for cheap fact-gathering (verify what Haiku returns).
- Never print or commit anything from `.env`.
- Stay modest with Gemini usage (at most 10 images per live tick) and track Context.dev credits.

## Things learned the hard way

- A blocked page can return HTTP 200. Check content, not status.
- Context.dev's JSON-schema extraction reads the page as text and misses image attributes; use the `images` and `html` formats when the data lives in tags.
- A Context.dev monitor run requested while the first baseline run is in flight is skipped.
- Monitor endpoints report credits in the response body, not in the `X-Credits-Used` header.
- Full-page JSON extraction on a large page can take 45 seconds; keep it out of request paths.
- Format links are harder to find citations for than character links.
- Image sourcing needs its own lookup step. The Imgflip top-100 list matched only 3 of 31 mock memes, but Imgflip's template search (`https://imgflip.com/memesearch?q=<name>`, trying an alias on a miss) found a clearly matching template for 20 of 21. Use that as the first image lookup, then Wikipedia's page summary thumbnail.

## State of the mock data

- 31 nodes: 6 format-class roots, Wojak, Doge and Pepe families, a few templates, 2 specimens. 24 have real, reachable image URLs; the 6 roots and one specimen are deliberately image-less to exercise the no-image design.
- The specimen `specimen-chair-doomer` borrows Doomer's image as a stand-in; it is mock data, not a real match.
- Dates, quotes and source URLs in the fixtures are illustrative and not verified. Sightings for unidentified posts use real Lemmy posts.
- The consistency check passes as of this update.
