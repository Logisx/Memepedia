# Plan: duplicates, unstamped tiles, and memes missing from their tree

Written 2026-11-15 for an implementing model (Sonnet) working on this Windows machine **without**
the repo-root `.env`. Nothing here may touch production. The other programmer (who has `.env`)
runs the production steps afterwards from the new section you add to `claude_docs/TODO_WITH_ENV.md`
(Part E). Read this whole file before starting.

## What was found (from the live API, 733 sightings, 2026-11-15 morning)

| Problem | Evidence | Root cause |
|---|---|---|
| Tiles with **no stamp at all** | 207 sightings are `unclassified`; `SightingTile.tsx` `Stamp` returns `null` for that state | (a) ~143 have a vision label with `is_meme=false`: the prompt (`llm.py` `_VISION_PROMPT`) tells Gemini a "screenshot of text" is not a meme, so programmer-humour and comic posts from meme communities land here. (b) ~50 have **no vision label at all**: `live._download_image` failed, so Gemini never saw them, and they are never retried (the post URL is "known" from then on). (c) Unknown number: `store.delete_nodes` and `store.expire_specimens` turn a deleted specimen's sightings into `unclassified` even when they are memes |
| Why images were not read | Tested by hand | `preview.redd.it/...?width=140&amp;...&crop=1:1` thumbnails return **403** (`reddit.py` `_PREVIEW_IMAGE_RE` fallback; `&amp;` is also never unescaped) while `https://i.redd.it/<same file>` returns 200. GIFs (`image/gif`) and AVIF (`lemmy.zip`, `image/avif`) are rejected by `_ALLOWED_MIME`; GIFs are also often over the 5 MB cap (one was 11 MB). Lemmy `.../api/v3/image_proxy?url=<real url>` wrappers |
| **Duplicates** on the wall | 11 groups with a byte-identical `image_url` (Lemmy cross-posts, e.g. `cm0002` on literature.cafe + `join` on lemmy.ml; one author posting twice 4 s apart). Reddit cross-posts by the **same author** to r/memes + r/dankmemes with **different** `i.redd.it` uploads (`G-5-0` "It had a good run", `PR0CR45T184T0R` "I will die on this hill") | `sightings.post_url` is the only uniqueness rule; every copy gets its own Gemini call and can get a different stamp. Title alone is NOT a safe key: dozens of distinct r/me_irl posts are titled `me_irl` |
| **Jensen Huang memes not shown together in a tree** | `/api/tree/jensen-huang`: `family_ids = ["jensen-huang"]`, one link (format → `reaction-image`), 21 resolved sightings in the archive | (1) The family map (`FamilyMap` / `familyLayout.ts`) draws **only nodes** of the character-line family. Jensen Huang has no character relatives, so the map is one lonely card plus "No relatives on record yet", and his 21 posts are only a list in the side panel. (2) `store.sightings_for_node` has `limit=12`, so 9 of the 21 never reach the page. (3) A post showing Jensen in another template (e.g. Drake) is stamped with that template (template guess wins over subject in `live.match_label`) and never appears on his page. (4) Jensen posts like "POV: you're Jensen Huang", "Performative Huang supporter", "NVidia harem Rule" are still `pending`, and the post titled "Jensen Huang" is `unclassified`: there is no rule that uses the post title |

Decision taken for the plan (change only if the owner says otherwise): every wall tile gets a stamp.
Non-template posts get a muted **"one-off"** stamp rather than being hidden.

## Ground rules

- Branch from an up-to-date `main`: `git checkout main && git pull && git checkout -b feat/dedupe-stamps-tree`.
- Never create or use a repo-root `.env`. Never run a script against `DATABASE_URL`. All scripts you
  write must print `db.describe_target()` first and be a **dry run unless `--apply`** (copy the
  shape of `backend/scripts/rematch.py`).
- Commits: plain messages, **no `Co-Authored-By` trailer**. One commit per Part is fine.
- Match the existing style: docstrings on every public function, `from __future__ import annotations`,
  type hints, Ruff line length 100, strict mypy on `memepedia` and `scripts`.
- Schema changes go in `backend/memepedia/schema.sql` as idempotent `ALTER TABLE ... ADD COLUMN IF
  NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` (that file is the migration; it runs on every start).
- **How to run the backend checks on this machine.** The test database (pgserver) cannot run on
  Windows or on `/mnt/c`, so sync a copy into WSL's own filesystem and run there (verified: 354 tests
  pass this way). From PowerShell, with **single** quotes:
  ```powershell
  wsl -e bash -lc 'rsync -a --delete --exclude .venv --exclude .pgdata --exclude node_modules --exclude .git /mnt/c/Users/gluck/IdeaProjects/Memepedia/ ~/memepedia-wsl/ && cd ~/memepedia-wsl/backend && export UV_PROJECT_ENVIRONMENT=$HOME/.venvs/memepedia UV_LINK_MODE=copy && ~/.local/bin/uv run python -m pytest -q && ~/.local/bin/uv run ruff check . && ~/.local/bin/uv run mypy memepedia scripts'
  ```
  Re-run the rsync every time (it is part of the command). Edit files only in the Windows checkout.
- Frontend checks: from `web/`, `npm run build` and `npx oxlint` (see `web/package.json` for the
  exact script names) must pass.
- Contract changes: `contract/types.ts` and `backend/memepedia/models.py` must stay in step, and every
  sighting object in `contract/fixtures/*.json` must get the new fields. Run
  `python contract/fixtures/check_fixtures.py` and `tests/test_contract.py`.

---

## Part A: read every image (fixes the ~50 never-read tiles)

### A1. Pillow and a new module `backend/memepedia/imageprep.py`

- Add `"pillow>=11.3"` to `backend/pyproject.toml` dependencies and update `uv.lock` (run
  `uv lock` in the WSL copy, then copy `uv.lock` back: `cp ~/memepedia-wsl/backend/uv.lock
  /mnt/c/Users/gluck/IdeaProjects/Memepedia/backend/uv.lock`). Check AVIF works:
  `uv run python -c "from PIL import features; print(features.check('avif'))"` must print `True`.
  If it prints `False`, keep AVIF in the allowed list anyway; `prepare` will raise and the miss is
  recorded (A3), never crashing a tick.
- Also add `pillow` to the Modal image in `backend/deploy.py` if that file lists packages explicitly
  (read it; if it installs from `pyproject.toml`, nothing to do).
- Module contents:
  ```python
  INPUT_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"}
  MAX_SIDE = 1600

  class ImageError(Exception): """The bytes could not be decoded as an image."""

  @dataclass(frozen=True)
  class Prepared:
      data: bytes        # always JPEG
      mime: str          # always "image/jpeg"
      fingerprint: str   # 64 hex chars, see dhash()

  def prepare(raw: bytes) -> Prepared:
      """Decode any supported image (first frame of an animation), flatten to RGB on white,
      shrink so the long side is at most MAX_SIDE, re-encode as JPEG quality 85."""

  def dhash(img: Image.Image) -> str:
      """256-bit difference hash: grayscale, resize to 17x16 (LANCZOS), bit = pixel > right
      neighbour, row by row; returned as 64 lowercase hex chars."""

  def distance(a: str, b: str) -> int:
      """Hamming distance between two fingerprints: bin(int(a,16) ^ int(b,16)).count("1")."""
  ```
  Use `Image.open(io.BytesIO(raw))`, then `img.seek(0)` for animations, `ImageOps.exif_transpose`,
  convert `P`/`LA`/`RGBA` by pasting onto a white RGB canvas. Wrap every Pillow error
  (`UnidentifiedImageError`, `OSError`, `ValueError`, `Image.DecompressionBombError`) in `ImageError`.
  Compute the fingerprint from the **decoded first frame before shrinking**.

### A2. Downloading: `live._download_image`

- Accept any mime in `imageprep.INPUT_MIME`. Also accept `application/octet-stream`, or a missing
  content type, and let `prepare` decide.
- Raise the download cap to 25 MB (`_MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024`), stream the response
  (`client.stream("GET", url)`) and stop reading once the cap is passed.
- Return a result that says **why** it failed, instead of bare `None`:
  `download_image(url) -> tuple[bytes, None] | tuple[None, str]`, where the string is one of
  `"http_<status>"`, `"network"`, `"unsupported:<mime>"`, `"too_large"`, `"undecodable"`.
- Leave `identify()` (the dropped-image route) with its own 5 MB limit, but run its bytes through
  `imageprep.prepare` too, so a dropped GIF works.

### A3. Remember why an image was not read

- `schema.sql`: `ALTER TABLE sightings ADD COLUMN IF NOT EXISTS look_error text;`
- `store.insert_sighting` gets a `look_error: str | None = None` parameter. `_save_looked` passes the
  download failure reason when vision is `None`.
- `models.Sighting` / `contract/types.ts` `Sighting` get `read: boolean`, which is true when the
  row's `vision IS NOT NULL`. Set it in `store._row_to_sighting` (`read=row.get("vision") is not None`).
  Add the doc comment in `types.ts`: "false = the image could not be fetched or decoded; the post
  was never looked at".

### A4. Sources

- `sources/reddit.py`: after picking an image URL, `html.unescape` it. Then, if it matches
  `^https://preview\.redd\.it/([A-Za-z0-9]{8,20}\.(?:jpe?g|png|gif|webp))(?:\?.*)?$`, rewrite it to
  `https://i.redd.it/<group 1>`. Leave any other preview URL as it is (it may fail; A3 records it).
  The rewritten URL is what is saved, so the wall shows the full image instead of "specimen missing".
- `sources/lemmy.py`: if `post["url"]` has the path `/api/v3/image_proxy` and a `url` query
  parameter, use `urllib.parse.parse_qs(...)["url"][0]` as `image_url`. `_is_image_post` must look
  at the unwrapped URL.
- Tests (`tests/test_sources_parsing.py`): the preview rewrite, `&amp;` unescaping, a preview URL
  that must NOT be rewritten (e.g. `.../some-title-v0-abc123.jpeg?...`), the image_proxy unwrap.
- Tests (new `tests/test_imageprep.py`, images made in memory with Pillow): a 2-frame GIF gives a
  JPEG of frame 0; an RGBA PNG flattens to white; a 4000x1000 image comes out 1600x400; the same
  image re-encoded at JPEG quality 60 is within distance 10; two different random-noise images
  are more than 60 apart; garbage bytes raise `ImageError`. Skip the AVIF case with
  `pytest.mark.skipif(not features.check("avif"))`.

### A5. `backend/scripts/relook.py` (run later on production by the other programmer)

```
uv run python scripts/relook.py [--apply] [--max 80] [--not-memes] [--orphans]
```
- **Default target:** sightings with `vision IS NULL AND duplicate_of IS NULL`, newest first.
  - Dry run: download and `prepare` each one (no Gemini) and print `id  ok|<reason>  image_url`,
    then a count by reason. Also rewrite a stored preview.redd.it or image_proxy URL with the A4
    helpers (move them into small public functions, e.g. `reddit.full_image_url`,
    `lemmy.unwrap_proxy`). Print the rewrite; save it only with `--apply`.
  - `--apply`: for each that downloads, at most `--max` of them, call `llm.vision_label` with
    `_archive_context()`, pass the result through `live._guardrail` (the Gemma NSFW check, added
    on 2026-11-15 just before this plan; it costs a second call per image, so count `--max` as images, not
    calls), then `classify` (with the title rule from D3), and save with a new
    `store.update_sighting_label(sid, vision, node_id, state, nsfw, image_url, fingerprint,
    look_error)`. For one that still fails, store `look_error`. Stop cleanly on
    `llm.GeminiCapReached` (or whatever the budget exception is called in `llm.py`) and print how
    far it got.
- **`--not-memes`:** instead targets `state = 'unclassified' AND vision IS NOT NULL AND
  (vision->>'is_meme') = 'false'`. It re-labels them with the new prompt (B2). Same `--max`, same
  dry run (which only lists them).
- **`--orphans`:** instead targets `state = 'unclassified' AND node_id IS NULL AND (vision->>'is_meme')
  = 'true'` (the leftovers of expired specimens) and sets them to `pending`. No Gemini call. The dry
  run lists them.
- It must print the database target first and end with `dry run: nothing changed (add --apply)`
  or `changed: N`.
- Tests (`tests/test_relook.py`, monkeypatching the downloader and `llm.vision_label` the way
  `tests/test_rematch.py` and `tests/test_live.py` do): a dry run changes nothing; `--apply` saves a
  label and stamps; a failed download stores `look_error`; `--orphans` flips state; `--max` is
  honoured.

---

## Part B: every tile has a stamp

### B1. Expired specimens no longer strip a meme's stamp

In `store.delete_nodes` and `store.expire_specimens`, replace
`UPDATE sightings SET node_id = NULL, state = 'unclassified' WHERE node_id = ANY(%s)` with:
```sql
UPDATE sightings
SET node_id = NULL,
    state = CASE WHEN (vision->>'is_meme') = 'true' THEN 'pending' ELSE 'unclassified' END
WHERE node_id = ANY(%s)
```
Update both docstrings. Add a test in `tests/test_store.py`: a deleted node's meme sighting
becomes `pending`, and its non-meme sighting becomes `unclassified`.

### B2. A looser `is_meme` in the vision prompt

In `llm._VISION_PROMPT`, replace the sentence
"Return is_meme=false for a plain photo, a screenshot of text, news, or non-meme art." with:
"Every image comes from a meme community. Return is_meme=true for anything posted as humour:
captioned images, comics, joke screenshots of text or code, edited photos, even when no known
template is used. Return is_meme=false only for a plain photo or artwork with no joke, news, or an
advert." Do not touch the rest of the prompt. If `tests/test_llm_parsing.py` asserts on prompt
text, update it.

### B3. The stamp on the wall (`web/src/components/SightingTile.tsx`)

The `Stamp` component handles four cases (same position and rotation as today):

| Case | Text | Style |
|---|---|---|
| `resolved` | `family: <name>` | unchanged |
| `pending` | `unidentified` | unchanged |
| `unclassified` and `read` | `one-off` | `border-2 border-dashed border-ink-soft text-ink-soft` |
| `unclassified` and not `read` | `not read yet` | `border-2 border-dotted border-ink-soft text-ink-soft` |

Then give every tile the `pt-5` caption padding, since every tile now has a stamp, and keep the
grayscale treatment only for the `not read yet` case. Check the side panel's sightings list
(`SidePanel.tsx`) does not assume `unclassified` means "no stamp".

---

## Part C: one post, one tile (duplicates)

### C1. Schema

```sql
ALTER TABLE sightings ADD COLUMN IF NOT EXISTS duplicate_of text REFERENCES sightings (id) ON DELETE SET NULL;
ALTER TABLE sightings ADD COLUMN IF NOT EXISTS fingerprint text;
CREATE INDEX IF NOT EXISTS sightings_image_url_idx ON sightings (image_url);
CREATE INDEX IF NOT EXISTS sightings_duplicate_idx ON sightings (duplicate_of);
```

### C2. The duplicate rule: new module `backend/memepedia/dedupe.py`

Pure functions, no I/O, fully unit-tested:
```python
GENERIC_TITLES = {"", "me irl", "meirl", "me_irl", ".", "meme", "memes", "dankmemes", "title"}
WINDOW = timedelta(days=7)

def norm_title(title: str) -> str:  # resolver.normalize, but keep "meme" words; "" for generic titles
def same_post(a: Candidate, b: Candidate) -> bool:
    """Two sightings are one post when:
    D1 their image_url is identical (after the A4 rewrites), or
    D2 their fingerprints are within 4 bits (of 256), or
    D3 their fingerprints are within 12 bits AND (same non-null author OR same non-generic norm_title)
    and, for D2 and D3, posted_at is within WINDOW of each other."""
def find_original(c: Candidate, others: Iterable[Candidate]) -> Candidate | None:
    """The earliest-posted `other` that is the same post as `c` (ties: smaller id)."""
```
`Candidate` is a small frozen dataclass: `id, image_url, fingerprint, author, title, posted_at`.
Tests (`tests/test_dedupe.py`) must cover:
- identical URL with different authors is a duplicate;
- the same author and title with fingerprints 8 bits apart is a duplicate;
- two `me_irl` posts from different authors 10 bits apart are NOT duplicates;
- two posts 3 bits apart but 30 days apart are NOT duplicates;
- `None` fingerprints only ever match by D1.

### C3. Use it in the live loop (`live.py`)

Split the LOOK step into three phases. This way a duplicate costs no Gemini call, even when both
copies arrive in the same batch:
1. **Fetch (parallel, as today):** download, then `imageprep.prepare` each post in the batch,
   giving `(post, prepared | None, look_error | None)`.
2. **Dedupe (sequential):** load candidates with a new `store.dedupe_candidates(since=now - 7 days)`
   (non-duplicate sightings: `id, image_url, fingerprint, author, title, posted_at, state,
   node_id`), plus the posts already handled earlier in this batch. For each post call
   `dedupe.find_original`.
   - If it is a duplicate: `store.insert_sighting(..., duplicate_of=orig.id, fingerprint=...)`,
     copying `state`, `node_id`, `vision` and `nsfw` from the original. No Gemini call. Count it
     in a new `TickReport.duplicates` field.
   - If it is a duplicate of a post earlier **in the same batch**, insert it after that original
     has been saved.
3. **Look (parallel):** `vision_label` only for the posts that are not duplicates, sending
   `prepared.data` / `prepared.mime`. Then save as today, now with `fingerprint` and `look_error`.

`store.insert_sighting` gains `fingerprint: str | None = None` and `duplicate_of: str | None = None`.
Update the `TickReport(...)` constructions in `live.py` (several error paths build one positionally)
and any tests that build one.

### C4. A stamp on the original follows to its copies

- `store.attach_sightings(ids, node_id)`: also update rows `WHERE duplicate_of = ANY(ids)`.
- `rematch.py` and `relook.py`: only ever select `duplicate_of IS NULL` rows, and apply through
  `attach_sightings` / `update_sighting_label`. `update_sighting_label` must copy the new
  state/node_id/nsfw to the row's duplicates too.

### C5. Hide duplicates everywhere they would be counted or shown

Add `duplicate_of IS NULL` (as `s.duplicate_of IS NULL` where the alias is `s`) to:
- `store._wall_query` (the wall and its paging), `store.sightings_for_node` (the tree),
  `store.pending_sightings` and `store.pending_with_vision` (clustering and rematch: two accounts
  cross-posting one image must not count as two authors);
- the `sightings_24h` / `sightings_7d` subqueries in `_NODE_BASE_SQL`;
- the "Rising" query near `store.py:637`;
- the week queries (search `store.py` for every `FROM sightings` / `_WALL_SELECT`; the full list on
  2026-11-15 is lines 35, 40, 291, 418, 494, 505, 540, 618, 637, 677). Leave `known_post_urls`,
  `sightings_needing_nsfw_label`, `counts` and `expire_specimens` as they are.

Tests: a wall/tree test that inserts an original and a duplicate and sees one tile. A
`tests/test_live.py` test where a batch holds two copies of one image: one Gemini call, two rows,
the second with `duplicate_of` set and the same stamp.

### C6. `backend/scripts/dedupe.py` (for existing data; run later on production)

```
uv run python scripts/dedupe.py [--apply] [--workers 8]
```
1. **Fingerprint backfill:** for every non-duplicate sighting with `fingerprint IS NULL`, download
   and `prepare` (thread pool, `--workers`). Store the fingerprint, or set `look_error` if it
   fails. This runs **in both modes**, because it only adds data and costs no paid calls (about 750
   downloads). Print progress every 50.
2. **Grouping:** walk sightings by `posted_at` ascending and use `dedupe.find_original` against
   the ones walked so far (union-find or a simple "first match wins" is fine). Within each group,
   pick the **keeper** as the best state (`resolved` > `pending` > `unclassified`), then the
   earliest post.
3. **Output:** print each group: the keeper first, then each duplicate with the rule that matched
   (D1/D2/D3) and the bit distance, then totals. Save nothing in a dry run.
4. **`--apply`:** set `duplicate_of = keeper.id` on the others and copy the keeper's
   `state`/`node_id` to them (keep their own `vision`).

Tests (`tests/test_dedupe_script.py`, with the downloader monkeypatched): a dry run writes only
fingerprints; `--apply` marks the right rows; the keeper rule prefers a resolved copy.

---

## Part D: a meme's posts appear together in its tree (the Jensen Huang case)

### D1. More posts, and the ones that show him in another template

`store.sightings_for_node(node_id, limit=48, include_sensitive=False, names=None)`:
- `limit` default goes from 12 to 48.
- When `names` (lower-cased name and aliases) is given, which `api.get_tree` does **only for
  `kind == "character"` nodes**, also return resolved sightings stamped with **another** node
  whose vision subjects name this character:
  ```sql
  WHERE s.duplicate_of IS NULL AND (
    s.node_id = %(id)s
    OR (s.state = 'resolved' AND s.node_id <> %(id)s AND EXISTS (
          SELECT 1 FROM jsonb_array_elements_text(COALESCE(s.vision->'subjects', '[]'::jsonb)) AS subj
          WHERE lower(subj) = ANY(%(names)s)))
  ) {sensitive_filter}
  ORDER BY s.posted_at DESC LIMIT %(limit)s
  ```

### D2. Group them by variant

- Add `variant: string | null` to `Sighting` in `contract/types.ts` (doc: "tree only: which
  template or family this post uses, when it is not the selected meme itself; null elsewhere and
  when unknown") and to `models.Sighting` (default `None`).
- In `api.get_tree`, set `variant` on each returned sighting:
  - if its `node_id` is not the selected node, `variant` is its `node_name` (a cross-stamped post,
    e.g. "Drake Hotline Bling");
  - otherwise, if its vision `template_guess` is set and `resolver.normalize(guess)` is not the
    normalised name or any alias of the selected node, `variant` is the guess as written;
  - otherwise `None`.

  This needs the vision JSON, so either have `sightings_for_node` return rows that keep `vision`,
  or add a sibling store function returning `(Sighting, vision)` pairs. Do not add `vision` to the
  contract.
- `GET /api/wall` and the rest leave `variant` as `None`.
- Tests (`tests/test_contract.py` or a new `tests/test_tree_sightings.py`): a character node's
  tree includes a post stamped to another node whose subjects name it, with `variant` = that node's
  name; a non-character node's tree does not include such posts; the limit is 48.

### D3. The title rule, for posts like "POV: you're Jensen Huang"

- In `resolver.Matcher`, add `def title(self, title: str) -> str | None`. It returns the **single**
  node whose name or alias appears in `normalize(title)` as a whole-word phrase (pad both strings
  with spaces and use `f" {name} " in f" {title} "`). It only counts names that are at least 2 words,
  or a single word of at least 8 characters, and that are not in `_GENERIC_SUBJECTS`. It returns
  `None` when no node or more than one node matches.
- In `live.match_label`, add `title: str | None = None` and a fourth rule after the subject rule:
  `if t.titles and title and label.is_meme and (node_id := m.title(title))`. That gives
  `LabelMatch(node_id, "title")` (extend the `via` Literal).
- In `Thresholds`, add `titles: bool`, from a new setting `match_titles` / env
  `VISION_MATCH_TITLES` (default on), added to `config.py` and to the env list in
  `backend/deploy.py` next to `VISION_MATCH_SUBJECTS`.
- Pass the post title in `live._save_looked` (`result.post.title`), in `rematch.py` (add `title`
  to the `pending_with_vision` SELECT), and in `relook.py`. Leave `identify()` without a title.
- Tests (`tests/test_resolver.py`, `tests/test_live.py`): "POV: you're Jensen Huang" matches;
  "Performative Huang supporter" does NOT (a single 5-letter word); a title naming two nodes gives
  `None`; `VISION_MATCH_TITLES=0` turns the rule off; the subject and template rules still win
  first.

### D4. Draw the posts in the family map (`web/src/lib/familyLayout.ts`, `FamilyMap.tsx`, `Lineage.tsx`, `SidePanel.tsx`)

- `familyLayout.ts`: add a third node kind,
  `{ id: 'posts:<key>', kind: 'posts', x, y, label: string, count: number, thumb: string, nodeId: string | null }`.
  Build the groups from `tree.sightings`, using only `nsfw === false` ones unless the caller says
  otherwise (pass `showSensitive` in):
  - key = `variant ?? '__own'`, sorted by count (largest first);
  - label = the variant, or `"in the wild"` for `__own`;
  - thumb = the newest post's `image_url`;
  - `nodeId` = the sighting's `node_id` when it differs from the selected meme, else `null`.

  Show at most 6 groups; fold the rest into one `"other posts"` group with their summed count.
  Add each group as a dagre child of the **selected** node, with an edge `{ inferred: false,
  onPath: false }` plus a new `kind: 'posts'` flag on `FamilyEdge`.
- `FamilyMap.tsx`: a `PostsBox` node type, the same size as `MemeBox` (`NODE_W` x `NODE_H`). It holds
  the 68px thumbnail (`object-cover`), the label (line-clamp-2) and `"N posts"` in `font-type`, with
  a dotted border (`border-2 border-dotted border-ink`). Draw `posts` edges with
  `strokeDasharray: '2 5'` in `var(--color-ink-soft)`. Add a legend row "posts seen" when any are
  drawn. On click:
  - if `nodeId` is set, `navigate('/meme/' + nodeId)`;
  - otherwise call a new prop `onPostsClick(key)`.
- `Lineage.tsx`: keep `const [postsFilter, setPostsFilter] = useState<string | null>(null)`. Pass
  `onPostsClick={setPostsFilter}` to `FamilyMap`, and pass `filter` plus `onClearFilter` to
  `SidePanel`. Show the "No relatives on record yet" message only when the family is alone **and**
  there are no sightings. Otherwise, for a lone family, show "No recorded relatives yet: the posts
  below are this meme seen in the wild."
- `SidePanel.tsx`: when `filter` is set, switch to the Sightings tab and show only the sightings
  whose `variant ?? '__own'` equals it, with a "Showing: <label> · show all" line that clears it.
- Check the map by hand with `npm run dev` against the contract fixtures. Add a fixture sighting with
  a `variant` to `contract/fixtures/tree-doomer.json`, or similar, so a group shows. On a phone width
  the selected meme must still be the focus (`focusSelected` in `FamilyMap.tsx`).

---

## Part E: hand-over for the other programmer

### E1. `backend/scripts/diagnose.py` (read-only, no paid calls)

```
uv run python scripts/diagnose.py [--name "Jensen Huang"]
```
Prints, after the database target:
1. A count of sightings by `state` x (`vision IS NULL`) x `nsfw` x (`duplicate_of IS NULL`). Guard
   the new columns: check `information_schema.columns` and leave a column out if it doesn't exist
   yet, so the script also works **before** the deploy.
2. The `look_error` breakdown (when the column exists).
3. The orphan count: `state = 'unclassified' AND node_id IS NULL AND vision->>'is_meme' = 'true'`.
4. Groups with an identical `image_url`: their number, and the first 10.
5. With `--name`, find the node by `Matcher.exact`, then list every sighting that is not stamped to
   it but whose title, `vision->>'template_guess'` or `vision->'subjects'` contains the name or an
   alias (case-insensitive `ILIKE`). For each, show `state`, `node_id`, title, `template_guess`,
   `confidence`, `subjects` and `is_meme`.

It never writes and never calls Gemini or Context.dev. Add a smoke test that runs it on the test
database.

### E2. Add this section to the **top** of `claude_docs/TODO_WITH_ENV.md`

Put it directly under the title. Move the existing body under a heading
`## Earlier rollout (2026-11-14, kept for reference)`. Fill in the real branch name, PR number
and test count, and fix any step whose details changed while you were building.

```markdown
## Rollout 2026-11-15: duplicates, stamps on every tile, posts in the tree

Branch `feat/dedupe-stamps-tree` (PR #<n>). Everything below runs from `backend/` with the repo-root
`.env`, so it hits **production**. Do the steps in order and keep every output file in `backend/.data/`
(git-ignored). Paid calls in total: at most ~160 Gemini/Gemma calls (step 5: 80 images, two calls each)
plus an optional ~300 (step 7);
**no Context.dev credits**.

### 0. Before touching anything
- [ ] Back up production: `pg_dump -Fc "$DATABASE_URL" -f backend/.data/before_dedupe_2026-11-15.dump`
      (pg_dump path: see "Earlier rollout" step 0).
- [ ] `git fetch && git checkout feat/dedupe-stamps-tree && git pull`, then `uv sync` (adds Pillow).
- [ ] `uv run pytest -q`, `uv run ruff check .`, `uv run mypy memepedia scripts` (Linux/WSL;
      expect <N> tests to pass). `uv run python -c "from PIL import features; print(features.check('avif'))"`
      should print True.
- [ ] `uv run python scripts/budget.py status`: note the Gemini calls in the last 24 h.
- [ ] Read-only snapshot **before** anything changes:
      `uv run python scripts/diagnose.py --name "Jensen Huang" | tee .data/diagnose_before.txt`.
      Paste this file to the owner; it tells us what the Jensen Huang posts were labelled as.

### 1. Get the code live
- [ ] Get the PR merged into `main` (owner's OK), then `git checkout main && git pull`.
- [ ] Optional: `VISION_MATCH_TITLES=1` is the default; set `VISION_MATCH_TITLES=0` in `.env` only to
      turn the new title rule off.
- [ ] Deploy from an up-to-date `main`: `.\backend\deploy.ps1` (Windows) or the Linux/WSL steps in
      "Earlier rollout" step 2. The new columns (`duplicate_of`, `fingerprint`, `look_error`) are added
      on the first start; that is safe and additive.
- [ ] Check: `<PUBLIC_BASE_URL>/api/health` is 200; the wall loads; every tile has a stamp
      (`family: …`, `unidentified`, `one-off`, or with NSFW on `not read yet`).

### 2. Mark existing duplicates (no paid calls, ~750 image downloads)
- [ ] Dry run (it also saves image fingerprints, which is safe):
      `uv run python scripts/dedupe.py | tee .data/dedupe_dry.txt`. Expect roughly 10 to 20 groups.
- [ ] Open 5 groups from the output and check each really is the same picture. If any is not,
      stop and tell the owner (the thresholds in `memepedia/dedupe.py` need tightening).
- [ ] `uv run python scripts/dedupe.py --apply | tee .data/dedupe_apply.txt`.
- [ ] On the wall: the cross-posted "Fall Guy", "Oh, behave!" and "It had a good run" now show once.

### 3. Give expired specimens' posts their "unidentified" stamp back (no paid calls)
- [ ] `uv run python scripts/relook.py --orphans` (dry run, lists them), then the same with `--apply`.

### 4. Re-read the images that were never read: dry run (no paid calls)
- [ ] `uv run python scripts/relook.py | tee .data/relook_dry.txt`. Check that most rows are now `ok`
      (the GIFs, AVIFs and Reddit thumbnails). The ones still failing are listed by reason.

### 5. Re-read them for real (at most 80 Gemini calls)
- [ ] `uv run python scripts/relook.py --apply --max 80 | tee .data/relook_apply.txt`.

### 6. Re-match pending posts with the new title rule (no paid calls)
- [ ] `uv run python scripts/rematch.py | tee .data/rematch_dry.txt`. Read the `via title` lines
      hardest: open ~10 of those posts and check the stamp is right.
- [ ] `uv run python scripts/rematch.py --apply`.

### 7. Optional: re-label old "one-off" posts with the looser prompt (at most ~150 Gemini calls)
- [ ] `uv run python scripts/relook.py --not-memes` (dry run, lists them), then
      `uv run python scripts/relook.py --not-memes --apply --max 150`.
- [ ] Then `uv run python scripts/rematch.py` and `--apply` again.

### 8. Check, record, hand back
- [ ] `/meme/jensen-huang`: the family map shows "Jensen Huang" with post groups hanging under it
      ("in the wild", plus one per other template he appears in). Clicking a group filters the
      Sightings tab; a group naming another meme opens that meme. The side panel shows more than 12 posts.
- [ ] `uv run python scripts/diagnose.py --name "Jensen Huang" | tee .data/diagnose_after.txt` and
      send both diagnose files to the owner.
- [ ] Watch one or two live ticks in the Modal logs: `TickReport` now has `duplicates=`; a cross-post
      should show up there and not as a second tile.
- [ ] Update `claude_docs/STATUS.md` ("Done") with the numbers from steps 2 to 7.

### If something looks wrong
- Wrong title stamps: set `VISION_MATCH_TITLES=0` in `.env`, redeploy, and tell the owner which posts.
- Wrong duplicates: `UPDATE sightings SET duplicate_of = NULL WHERE id IN (...)` for the bad ones.
  Or, as a last resort, restore from the step-0 dump (`pg_restore --clean -d "$DATABASE_URL" <dump>`;
  this loses everything collected since).
```

### E3. Docs

- `claude_docs/STATUS.md`: under "In progress", add one line pointing at this plan and at the new
  TODO section. Fix the stale claim in "More seed relatives" that Jensen Huang got a family: he only
  has a format link to Reaction image.
- `README.md`: if it documents the stamps or the scripts, add `one-off` / `not read yet`, and add
  `relook.py`, `dedupe.py` and `diagnose.py` to the scripts table in `STATUS.md` ("Where everything is").

---

## Order of work and definition of done

1. Part A (A1 to A4, then A5 last, because it uses C and D3), then Part B, Part C and Part D (D1 to
   D3 backend, then D4 frontend), then Part E.
2. Run the full backend command (WSL) and the frontend build/lint after each Part. Commit per Part.
3. Done when:
   - all backend tests pass, Ruff and mypy are clean, and `check_fixtures.py` passes;
   - `npm run build` passes;
   - the map shows post groups for a fixture tree in `npm run dev`;
   - `TODO_WITH_ENV.md` has the new section at the top;
   - the branch is pushed, and a PR into `main` is open with a summary that links this plan. Do
     not merge it; the owner merges.
