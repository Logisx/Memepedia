# Frontend plan — the "experience" half

Owner: the frontend teammate. Branch: `web`. Folder: `web/`.
This plan is self-contained. Give it to your coding assistant as the starting prompt, one step at a time.

You need nothing from the backend to finish this plan. No API keys, no database, no Context.dev account. The app runs on the mock data in `contract/fixtures/` until the two halves are merged.

## 1. What Memepedia is

The open family tree of internet culture. Posts seen on social feeds minutes ago appear on a live wall, each stamped with the meme family it belongs to. Open any meme and see its line of descent back to its origin, with a quoted source on every link.

Vocabulary:
- **Node**: a meme format (a character, a template, a phrase, or a broad format class). Never a single post.
- **Sighting**: one post seen in the wild, attached to a node.
- **Link**: "child derives from parent" on one of two axes. `character` is who the meme is about; `format` is how it is built. A link is `cited` (has a verbatim quote and a source) or `inferred` (drawn dashed, labelled "citation needed").
- **Specimen**: a node newly detected from sightings, not yet established.

## 2. Ground rules

- Work only in `web/`. Do not edit `contract/` or `backend/`.
- Every data shape is in `contract/types.ts`. Import the types from there; do not redefine them.
- All data goes through one module, `web/src/data.ts`. Nothing else in the app fetches data.
  - `VITE_API_BASE` unset: serve the JSON files in `contract/fixtures/`.
  - `VITE_API_BASE` set: call the real endpoints listed in `contract/README.md`.
- Mock behaviour the data module must simulate:
  - Wall: shift all fixture timestamps so the newest sighting is about two minutes old. Hold back 10 sightings and release one every 6 to 10 seconds, so the wall visibly updates.
  - Trace: replay `trace-sample.json`, honouring each `delay_ms`.
  - Tree and related: serve the matching fixture; for an id with no fixture, fall back to `tree-wojak.json`.
- Commit after every numbered step in section 6.

## 3. Stack

Vite, React, TypeScript, Tailwind, `react-router`, `@xyflow/react` with `@dagrejs/dagre` for the family map, `motion` for animation. No state library; React state and one polling hook are enough. The build output is a static site.

## 4. Look and feel

A natural-history museum of the internet.
- Cream paper background, thin ink-coloured rules.
- A serif display face (Fraunces or similar) for names; a typewriter face for labels and dates.
- Each meme is a pinned specimen with a label: name, mock-Latin name in italics, "first recorded 2018".
- A node with no image is a typeset specimen card (name and Latin name large on paper). It must look deliberate, not broken.
- It will be shown on a projector: large type, large images, high contrast. Check every screen from three metres away.

## 5. Screens

### Lineage — `/meme/:id` (the most important screen)

- **Top 45% of the viewport: the line of descent.** A horizontal strip of 4 to 6 large cards, oldest on the left, the selected meme on the right. Each card: image, name, Latin name, year.
- Between two cards sits the link: quote and source for a cited link; a dashed connector with "citation needed" for an inferred one.
- On open, the cards flip in one by one, from the selected meme back through time.
- A toggle switches the strip between the character line and the format line (`descent.character`, `descent.format`).
- **Bottom 55%: the family map.** Top-to-bottom dagre layout of `family_ids`, drawing only `character` links.
  - At most 8 children per parent, plus a "+N" node that expands on click.
  - The path from the selected meme to the root is highlighted; inferred links are dashed.
  - Clicking a node navigates to it. The map fades in after the cards.
- Format links of the selected meme appear as chips ("format: Virgin vs. Chad") that navigate to that node.
- A side or footer panel with three tabs:
  - recent sightings of this meme;
  - History (the `history` list, pending proposals marked);
  - "Suggest a source": a form with URL and note that calls the proposals endpoint and shows the result.

### Wall — `/` (the home screen)

- Masonry grid of sightings, newest first.
- Each tile: the image, "spotted 6 min ago on Lemmy" (computed from `posted_at`, ticking), and a stamp. Resolved sightings are stamped "family: Wojak"; pending ones "unidentified"; unclassified ones carry no stamp.
- New sightings animate in at the top, one at a time. A small status line reads "watching N sources".
- Clicking a resolved tile opens the lineage of its node.
- Above the grid:
  - a search box with suggestions from the nodes endpoint;
  - a random button;
  - a drop zone for an image, which calls identify and then either opens the returned node or starts a trace.
- "This week in memes" strip above the grid, from the week endpoint: rising families with their counts, and new specimens.

### Trace — overlay or `/trace?q=`

Shown when a search has no match or a dropped image is unknown.
- Status events appear as lines in a field log.
- When the `chain` event arrives, draw the chain with dashed links.
- As `link` events arrive, turn the matching link solid and reveal its quote.
- On `done`, navigate to the lineage screen for that node.

### Related — `/related?a=&b=`

- Two meme pickers.
- Show the sentence from the response.
- Draw both paths meeting at the common ancestor: once for the character line, once for the format line when present.

## 6. Steps

Hours are a guide for one person with a coding assistant. Stop and commit at each checkpoint.

| Step | Hours | Work | Checkpoint |
|---|---|---|---|
| F0 | 0 to 1 | Scaffold Vite app, Tailwind, routing, theme tokens and fonts. Write `data.ts` with all mock behaviours. | Each route renders its raw fixture data as text |
| F1 | 1 to 5 | Lineage screen on `tree-doomer.json`. Then check it against `tree-swole-doge-vs-cheems.json` (two lines of descent) and `tree-wojak.json` (many children). | The three fixtures all look right; a null-image node looks deliberate |
| F2 | 5 to 8 | Wall with drip-in, stamps, search, random, drop zone, week strip. | Wall updates by itself; clicking a tile opens its lineage |
| F3 | 8 to 10 | Trace overlay replaying the sample stream. | Dashed chain appears, links turn solid, lands on lineage |
| F4 | 10 to 12 | Related screen; History and "Suggest a source" tabs. | Both related fixtures render, including the one with no shared character ancestor |
| F5 | 12 to 14 | Polish: animation timing, projector check, empty and error states, loading states. | Every screen passes the definition of done |
| Merge | 14 to 16 | Set `VITE_API_BASE` to the backend URL and walk the checklist in section 8. | Real data on every screen |

If time runs short, cut from the bottom: Related first, then the "Suggest a source" form, then the week strip. Lineage, Wall and Trace are the demo.

## 7. Definition of done for a screen

- Works on fixtures alone.
- No console errors.
- Handles a null image, an empty list and a failed request.
- Readable from three metres on a 1080p projector.

## 8. Merge checklist

The backend teammate provides one thing: a public base URL. Then:

1. Set `VITE_API_BASE` and reload. Check each screen in this order: nodes search, tree, wall, week, trace, identify, related, proposals.
2. For any screen that breaks, compare the real response with the fixture. A mismatch with `contract/types.ts` is a backend bug; report it, do not adapt the UI to it.
3. Real data will be messier than fixtures: longer names, missing dates, more missing images, families with one node. Fix what looks broken.
4. Build the static site and deploy it (any static host; the backend can also serve the built files).

An optional early check at about hour 8: point `VITE_API_BASE` at the backend for five minutes to catch contract mismatches early. Neither half waits on this.
