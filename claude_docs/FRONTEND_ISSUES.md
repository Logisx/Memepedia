# Issues found while building the frontend

Found 2026-11-14 while building `web/` against `contract/`. Nothing in `contract/` or `backend/` was changed; these are for the contract owner to decide. The frontend works around each one so it is not blocked.

Status: **open** (needs a decision or fix on the contract side), **handled** (frontend copes; low priority).

## Fixture and contract bugs

### 1. Wrong common ancestor in `related-swole-doge-vs-cheems-yes-chad.json` — open

- **What:** `format.ancestor_id` is `virgin-vs-chad`, but `format.path_a` is `["swole-doge-vs-cheems", "comparison"]` and `format.path_b` is `["yes-chad", "virgin-vs-chad"]`. `types.ts` says each path runs up to the ancestor, inclusive; here `path_a` stops at `comparison`, so the two paths do not meet.
- **Likely cause:** in `tree-swole-doge-vs-cheems.json`, `virgin-vs-chad` is a child of `comparison` (format link, cited). So the real common ancestor is `comparison`, and `path_b` should be `["yes-chad", "virgin-vs-chad", "comparison"]`.
- **Related:** the `sentence` in the same file is muddled ("Yes Chad shares the Virgin vs. Chad format lineage with Swole Doge vs. Cheems' Comparison roots") and does not name one ancestor.
- **Effect:** the Related screen draws "Swole Doge vs. Cheems → Comparison" and "Yes Chad" both pointing at a highlighted Virgin vs. Chad, which misstates the history.
- **Why it slipped through:** `check_fixtures.py` does not check that each path ends at `ancestor_id`.
- **Frontend handling:** paths are drawn as given; the ancestor is drawn once on the right and left off a row that already ends on it.
- **Suggested fix:** correct the fixture (ancestor `comparison`, longer `path_b`, a sentence naming `comparison`) and add the "path ends at ancestor" check to `check_fixtures.py`.

### 2. `identify.json` and `proposal.json` hold arrays, the contract says one object — open

- **What:** `types.ts` and `contract/README.md` define `IdentifyResponse` and `ProposalResponse` as single objects. Both fixtures are arrays of two (a known meme and an unknown one; an accepted proposal and a rejected one).
- **Frontend handling:** the mock in `web/src/data.ts` alternates between the two answers so both UI branches get exercised. This is mock-only behaviour.
- **Suggested fix:** say in `contract/fixtures/README.md` that these two files are lists of example responses, or split them into one file per case.

### 3. `delay_ms` in `trace-sample.json` is not defined — open

- **What:** the values are 0, 900, 1400, 2600, 4300, 5100. The contract does not say whether each is the gap since the previous event or the offset from the start.
- **Frontend handling:** treated as offset from the start, so the whole replay takes about 5 seconds. As gaps it would take about 14 seconds, too slow for the demo.
- **Suggested fix:** state "offset in ms from the start of the stream" in `contract/README.md`.

### 4. `trace-sample.json` chain contains a shortcut link — handled

- **What:** the `chain` event has three links for three nodes: Grug → Wojak, Wojak → Drawn Character, and Grug → Drawn Character. The third skips a generation.
- **Frontend handling:** the chain is drawn in the order of `nodes`, using only the links between neighbours. The shortcut is ignored.
- **Suggested fix:** either drop it from the fixture, or state in the contract that `chain.nodes` is ordered meme-first and only neighbour links are shown.

### 5. Ids with no tree fixture fall back to Wojak — handled

- **What:** the trace sample ends on `grug-early-man`, and the week strip links to `specimen-chair-doomer` and `specimen-glitch-label`. None has a `tree-<id>.json`. Per the frontend plan the mock then serves `tree-wojak.json`, so the page opens on Wojak, not the meme that was clicked or traced.
- **Frontend handling:** works as specified; it is a mock-only effect and the real backend will not do it.
- **Suggested fix:** add small tree fixtures for these three ids, so the demo path through the mock lands on the right meme.

## Tooling notes (not contract bugs)

- **TypeScript 7 rejects `baseUrl`.** The scaffold's `create-vite` pulls TypeScript 7; `tsconfig.app.json` therefore uses only `paths` for the `@contract` alias.
- **Vite and Tailwind versions:** Vite 8, Tailwind 4 (via `@tailwindcss/vite`), React 19, `react-router` 8. Pinned by `web/package-lock.json`.
- **Windows line endings:** git warns that LF will be replaced by CRLF in `web/` files; harmless.
