# Frontend brief (the "experience" half)

This is everything needed to build the Memepedia frontend without the backend. Give this file to your coding assistant as the starting prompt.

## What Memepedia is

The open family tree of internet culture. Posts seen on social feeds minutes ago are shown on a live wall, each stamped with the meme family it belongs to. Open any meme and see its line of descent back to its origin, with a quoted source on every link.

Vocabulary:
- **Node**: a meme format (a character, a template, a phrase, or a broad format class). Never a single post.
- **Sighting**: one post seen in the wild, attached to a node.
- **Link**: "child derives from parent" on one of two axes. `character` is who the meme is about; `format` is how it is built. A link is `cited` (has a verbatim quote and a source) or `inferred` (shown dashed, labelled "citation needed").
- **Specimen**: a node newly detected from sightings, not yet established.

## Ground rules

- Work only in `web/` on the `web` branch. Do not edit `contract/` or `backend/`.
- Every data shape is in `contract/types.ts`. Import the types from there; do not redefine them.
- The app must run with no backend. All data goes through one module, `web/src/data.ts`:
  - If `VITE_API_BASE` is unset, it serves the JSON files in `contract/fixtures/`.
  - If it is set, it calls the real endpoints listed in `contract/README.md`.
  - Nothing else in the app may fetch data.
- Mock behaviour the data module must simulate:
  - Wall: shift all fixture timestamps so the newest sighting is about two minutes old. Hold back 10 sightings and release one every 6 to 10 seconds so the wall visibly updates.
  - Trace: replay `trace-sample.json`, honouring each `delay_ms`.
  - Tree and related: serve the matching fixture; for an id with no fixture, fall back to `tree-wojak.json`.

## Stack

Vite, React, TypeScript, Tailwind, `react-router`, `@xyflow/react` with `@dagrejs/dagre` for the family map, `motion` for animation. No state library; React state and a small polling hook are enough.

## Look and feel

A natural-history museum of the internet. Cream paper background, a serif display face (Fraunces or similar) for names, a typewriter face for labels and dates, thin ink-coloured rules. Each meme is a pinned specimen with a label: name, mock-Latin name in italics, "first recorded 2018". A node with no image is a typeset specimen card (name and Latin name large on paper), which must look deliberate, not broken. It will be shown on a projector: large type, large images, high contrast.

## Screens, in build order

1. **Lineage** (`/meme/:id`) — the most important screen.
   - Top 45% of the viewport: the line of descent as 4 to 6 large cards in a horizontal strip, oldest on the left, the selected meme on the right. Each card: image, name, Latin name, year. Between two cards: the link, showing the quote and source for a cited link, or a dashed connector with "citation needed" for an inferred one. On open, the cards flip in one by one from the selected meme back through time.
   - A toggle switches the strip between the character line and the format line (`descent.character`, `descent.format`).
   - Bottom 55%: the family map. Top-to-bottom dagre layout of `family_ids`, drawing only `character` links. Cap children at 8 per parent and show a "+N" node that expands on click. Highlight the path from the selected meme to the root; dashed edges for inferred links. Clicking a node navigates to it. The map fades in after the cards.
   - Format links of the selected meme appear as chips ("format: Virgin vs. Chad") that navigate to that node.
   - Side or footer panel with tabs: recent sightings of this meme; History (the `history` list, pending proposals marked); "Suggest a source" form (URL and note) that calls the proposals endpoint and shows the result.
2. **Wall** (`/`) — the home screen.
   - Masonry grid of sightings, newest first. Each tile: the image, "spotted 6 min ago on Lemmy" (computed from `posted_at`, ticking), and a family stamp ("family: Wojak") for resolved sightings; pending ones are stamped "unidentified", unclassified ones carry no stamp.
   - New sightings animate in at the top one at a time. A small status line: "watching N sources".
   - Clicking a resolved tile opens the lineage of its node.
   - Above the grid: a search box (calls nodes search, shows suggestions), a random button, and a drop zone for an image (calls identify, then either opens the returned node or starts a trace).
   - "This week in memes" strip above the grid from the week endpoint: rising families with their counts, and new specimens.
3. **Trace** (overlay or `/trace?q=`) — shown when a search has no match or an image is unknown.
   - Consume the event stream: show status lines as a field log; when the `chain` event arrives draw the chain with dashed links; as `link` events arrive turn the matching link solid and reveal its quote; on `done` navigate to the lineage screen.
4. **Related** (`/related?a=&b=`)
   - Two meme pickers. Show the sentence from the response, and both paths meeting at the common ancestor, once for the character line and once for the format line when present.

## Definition of done for each screen

It works on fixtures alone, has no console errors, handles a null image and an empty list, and is readable from three metres on a 1080p projector.

## Order of work and checkpoints

1. Scaffold, data module with mock behaviours, routing, theme tokens.
2. Lineage screen on `tree-doomer.json`, then check it with `tree-swole-doge-vs-cheems.json` (two lines of descent) and `tree-wojak.json` (many children).
3. Wall with drip-in and the week strip.
4. Trace.
5. Related, History and "Suggest a source".

Commit after each numbered step.
