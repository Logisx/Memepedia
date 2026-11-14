# Plan: stamp more sightings (subject matching, two thresholds, re-match script)

Written 2026-11-14 for an implementing agent. Read `claude_docs/STATUS.md` first for the project rules.

## Goal

Fewer live sightings stay "pending". Three changes, all without extra Gemini calls per post:

1. **Subject matching**: when the template guess cannot stamp a post, stamp it by the character it depicts. Gemini already returns `VisionLabel.subjects`; nothing reads it today.
2. **Two confidence thresholds**: a guess that exactly matches an archive name or alias needs 0.7; any other guess keeps 0.85.
3. **Re-match script**: run the new matching over sightings already stored as pending, using the vision JSON saved with each one (no new image calls).

Out of scope: changing the "be conservative / return null" wording of the vision prompt, GIF support, auto-trace rules, the clock, monitors.

## How it works today (verified against the code)

- `live._tick` → `_look_one` (download + `llm.vision_label`) → `_save_looked` → `live.classify(label, min_confidence, resolve)` → `store.insert_sighting`.
- `live.classify` (`backend/memepedia/live.py:122`): not a meme → `unclassified`; `template_guess` with `confidence >= min_confidence` and `resolve(guess, description)` returns an id → `resolved`; otherwise `pending`.
- `resolver.resolve` (`backend/memepedia/resolver.py:75`): exact normalised match on name/alias first; otherwise fuzzy candidates (`NEAR_SCORE = 60`) put to `llm.same_or_new` (one Gemini text call), and a confirmed match is saved as an alias. It calls `store.name_index()` on every call.
- The threshold is `Settings.vision_min_confidence` (`VISION_MIN_CONFIDENCE`, default 0.85) in `backend/memepedia/config.py`.
- Other callers of the same logic: `scripts/backfill.py:62` calls `classify`; `live.identify` (`live.py:396-398`) repeats the threshold-and-resolve logic inline.
- The full `VisionLabel` is stored per sighting as JSON (`store.insert_sighting`, `Json(vision.model_dump(mode="json"))`). Older rows may be missing later-added fields such as `nsfw`.
- `sightings_24h` / `sightings_7d` are computed in `store._fetch_nodes` queries, so attaching sightings needs no counter refresh.
- `store.attach_sightings(ids, node_id)` sets `node_id` and `state = 'resolved'`.

## Step 1: settings

File: `backend/memepedia/config.py`.

Add two fields to `Settings`, **with defaults and after `webhook_secret`** (the test helper `_settings()` in `tests/test_live.py` builds `Settings` without them, and dataclass fields with defaults must follow those without):

- `vision_exact_min_confidence: float = 0.7`, read from `VISION_EXACT_MIN_CONFIDENCE`.
- `match_subjects: bool = True`, read from `VISION_MATCH_SUBJECTS` (truthy: `1/true/on/yes`, case-insensitive; unset means on).

In `get_settings()`, pass both from the environment, falling back to the defaults.

## Step 2: a Matcher in the resolver

File: `backend/memepedia/resolver.py`.

1. Pull the body of `resolve` (after the blank-name check) into `_resolve_in(index, name, hint, allow_llm) -> str | None`. `resolve()` becomes `_resolve_in(store.name_index(), ...)`. Behaviour must not change; the existing `tests/test_resolver.py` must pass untouched.

2. Add a stoplist of generic one-word names that must never stamp through subjects:
   ```python
   _GENERIC_SUBJECTS = frozenset({"cameraman", "cameramen", "haggis", "walter", "npc"})
   ```
   Compare **normalised** forms (`normalize(...)`). These are the risky one-word character names/aliases in the archive today (a food, a job, a first name, a game term).

3. Add a class:
   ```python
   class Matcher:
       """Name lookups for one batch of labels, with the archive index loaded once."""

       def __init__(self, index: NameIndex, kinds: Mapping[str, str], *, allow_llm: bool = True) -> None: ...
       @classmethod
       def from_store(cls, *, allow_llm: bool = True) -> Matcher: ...   # store.name_index() + store.node_kinds()
       def exact(self, name: str) -> str | None: ...                    # exact_match semantics, via a dict built once
       def near(self, name: str, hint: str | None) -> str | None: ...   # _resolve_in(self.index, name, hint, self.allow_llm)
       def subject(self, subjects: Sequence[str]) -> str | None: ...
   ```
   - `exact`: build `{normalize(known): node_id}` once, **keeping the first occurrence** for duplicate keys so it agrees with `exact_match` (which uses `next(...)` over the index in order).
   - `subject`: for each subject, skip blanks and anything whose normalised form is in `_GENERIC_SUBJECTS`. Look it up with `exact`, and keep the id only when `kinds[id] == "character"`. Exact matches only: no fuzzy matching and no LLM, because subjects are free text ("a man in a suit"). Return the id when **exactly one distinct** node id was found; return `None` for zero or for two or more (ambiguous, e.g. Wojak and Pepe in one image).
   - `near` with `allow_llm=False` must never call `llm.same_or_new`.

4. File `backend/memepedia/store.py`: add `node_kinds() -> dict[str, Kind]` (`SELECT id, kind FROM nodes`). Do not use `all_nodes()` for this, because it runs the sighting-count joins.

## Step 3: classification

File: `backend/memepedia/live.py`.

1. Add:
   ```python
   @dataclass(frozen=True)
   class Thresholds:
       exact: float      # guess equal to an archive name/alias
       near: float       # any other guess, resolved by fuzzy match + LLM
       subjects: bool    # whether subject matching is on

       @classmethod
       def from_settings(cls, s: Settings) -> Thresholds: ...
   ```

2. Add `match_label(label: VisionLabel, t: Thresholds, m: Matcher) -> str | None`, applying these in order and returning the first hit:
   1. `label.template_guess` and `label.confidence >= t.exact` → `m.exact(guess)`
   2. `label.template_guess` and `label.confidence >= t.near` → `m.near(guess, label.description)`
   3. `t.subjects` → `m.subject(label.subjects)`

   Step 3 does not look at `confidence`: that number is about the template guess, not the subjects.

3. Change `classify` to `classify(label, t: Thresholds, m: Matcher) -> tuple[str | None, SightingState]`: not a meme → `(None, "unclassified")`; else `match_label` → `resolved` or `(None, "pending")`.

4. `_save_looked(looked, thresholds, matcher, errors)`. In `_tick`, build `Thresholds.from_settings(settings)` and `Matcher.from_store()` once per tick, after the LOOK step. Keep the auto-trace candidate rule exactly as it is (`guess` and `confidence >= _AUTO_TRACE_MIN_CONFIDENCE` on a pending sighting).

5. Delete `_resolve` (`live.py:118`) if nothing else uses it.

6. `identify()`: replace lines 396-398 with `node_id = match_label(label, Thresholds.from_settings(settings), Matcher.from_store())`. Keep the NSFW early return and the rest of the response logic. Do not add an `is_meme` check here; identify currently has none.

7. `scripts/backfill.py:62`: switch to the new `classify` signature, building `Thresholds` and `Matcher` once in `backfill()` and passing them through `_save_one`. The `min_confidence` parameter goes away.

## Step 4: tell Gemini to use archive names for subjects

File: `backend/memepedia/llm.py`, `_VISION_PROMPT` (line 185). Change one sentence:

> `subjects lists the depicted characters, people or things.`

to

> `subjects lists the depicted characters, people or things; when one of them is a known name below, write that name verbatim.`

Nothing else in the prompt changes. This makes subject strings match archive names exactly instead of near-miss spellings.

## Step 5: re-match script

New file: `backend/scripts/rematch.py`. Follow the style of `scripts/set_nsfw.py` / `scripts/seed.py` (docstring with usage, `argparse`, `db.init_schema()`).

```
Usage: uv run python scripts/rematch.py [--apply] [--hours N] [--llm] [--max-llm N]
```

- Reads pending sightings that have a vision label: `SELECT id, vision FROM sightings WHERE state = 'pending' AND vision IS NOT NULL` (add `AND seen_at > now() - interval` when `--hours` is given). Put this query in `store.py` as `pending_with_vision(hours: int | None) -> list[db.Row]`; do not reuse `pending_sightings`, which always applies a window.
- Rebuilds each label with a new public `llm.parse_stored_vision(raw: Mapping[str, Any]) -> VisionLabel`. It is tolerant like `_parse_vision_label`: missing keys get defaults, and `structure_class` is kept as stored. Don't call the private `_parse_vision_label`, which needs roots.
- Matches with `match_label(label, Thresholds.from_settings(get_settings()), Matcher.from_store(allow_llm=args.llm))`.
- **Cost guard:** without `--llm` it makes no Gemini calls at all (exact and subject matching only). With `--llm`, at most `--max-llm` (default 50) guesses may reach the fuzzy+LLM step. Count them in the script: only call `match_label` with near-matching enabled while the count is under the cap, otherwise use a `Thresholds` with `near=2.0` so step 2 never fires. Print how many LLM-eligible guesses were skipped.
- **Dry run by default.** Print one line per new match: `sighting_id  node_id  via  guess-or-subjects`, where `via` is `exact`, `near` or `subject`. Have `match_label` return that alongside the id: either `tuple[str, str] | None` or a small `Match` dataclass. If you do this, update `classify`/`identify` to take the id. Then print totals per node and per `via`.
- With `--apply`, group by node id and call `store.attach_sightings(ids, node_id)`; print the number changed.
- Before doing anything, print which database it targets (host and database name from the configured URL, never the password). With a repo-root `.env` holding `DATABASE_URL`, that is **production**: see STATUS "Things learned the hard way", 17:25 entry.

## Step 6: tests

Run from `backend/`: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy memepedia scripts`. All three must stay clean. Tests use the local `memepedia_test` database (`tests/conftest.py`).

Known flaky: five tests in `tests/test_trace.py` call real Gemini when a key is present (STATUS "Still open"). Don't count them as regressions and don't fix them here.

Update `tests/test_live.py` (the `classify` tests at lines 67-104 use the old signature). Use a fake `Matcher`: a tiny class with `exact/near/subject` methods, or a real `Matcher` built from a hand-made index and kinds with `allow_llm=False`. Cover:

- not a meme → unclassified, and the matcher is never called
- exact match at confidence 0.75 → resolved (between the two thresholds)
- fuzzy-only guess at 0.75 → `near` not called → pending
- fuzzy guess at 0.9 → `near` called → resolved
- no guess, one character subject → resolved
- no guess, subjects naming two different characters → pending
- subject matching a template-kind node → pending
- stoplisted subject ("Haggis") → pending
- `subjects=False` in `Thresholds` → subject step skipped
- guess and subject both match different nodes → the guess wins

Add to `tests/test_resolver.py`:
- `Matcher.exact` agrees with `exact_match` on the existing parametrised cases
- `Matcher.near(..., allow_llm=False)` never calls `same_or_new`
- the duplicate-key rule (first occurrence wins)

Add `tests/test_rematch.py` (or extend `test_store.py`): insert two pending sightings into the test DB with stored vision JSON (one matching an existing fixture node exactly, one not). Run the script's core function (keep it importable: `def rematch(apply: bool, hours: int | None, llm: bool, max_llm: int) -> RematchReport`, with `main()` a thin wrapper). Assert that a dry run changes nothing and that `apply` resolves only the matching one. Also assert `parse_stored_vision` accepts a dict missing `nsfw`.

Update the existing tick tests (`test_tick_*`) only where the new signature forces it; their expected counts should not change.

## Step 7: docs

- `claude_docs/STATUS.md`: under "Running the backend", add the `rematch.py` row. Under "Decisions made", record the two thresholds (0.7 exact / 0.85 other), subject matching (exact, character-only, stoplist, `VISION_MATCH_SUBJECTS` to turn it off), and that the re-match script is dry-run by default and makes no Gemini calls without `--llm`.
- `backend/memepedia/live.py` module docstring, if it describes the 0.85 rule.

## Rules for the implementing agent

- Work on branch `bugfix/various-fixes` (or a branch off it). Never commit to `main`.
- Small commits, one per step or two. **No `Co-Authored-By` or other attribution lines in commit messages.**
- **Do not run `rematch.py --apply`, `seed.py`, a deploy or anything else against production.** With a repo-root `.env`, every script targets the hosted database. The owner runs those. Dry runs against production are also the owner's call; on your side, test only against the local test database.
- Never print or commit anything from `.env`.
- Don't change `NEAR_SCORE`, `_AUTO_TRACE_MIN_CONFIDENCE`, the auto-trace rules or anything outside the files named here without asking.

## After it lands (owner)

1. Measure where posts drop out (run on production):
   ```sql
   SELECT CASE
            WHEN vision IS NULL THEN '1 no image / download failed'
            WHEN NOT (vision->>'is_meme')::boolean THEN '2 not a meme'
            WHEN vision->>'template_guess' IS NULL THEN '3 no guess'
            WHEN (vision->>'confidence')::float < 0.85 THEN '4 low confidence'
            ELSE '5 guess not in archive'
          END AS reason, count(*)
   FROM sightings WHERE state <> 'resolved' GROUP BY 1 ORDER BY 1;
   ```
2. Find the recurring subjects worth adding as character nodes (e.g. Jensen Huang for the Nvidia memes):
   ```sql
   SELECT s AS subject, count(*) FROM sightings, jsonb_array_elements_text(vision->'subjects') s
   WHERE state = 'pending' GROUP BY 1 ORDER BY 2 DESC LIMIT 60;
   ```
   Add the real recurring ones to `seed.json` as `kind: "character"` nodes with a format link. Facts get checked like any seed entry. Then run `seed.py --steps families,images`.
3. Deploy (only then do live ticks use the new logic). Then run `rematch.py` as a dry run, read the list, spot-check about 20 matches by opening the posts, and run `--apply`.
4. If subject matching stamps badly, set `VISION_MATCH_SUBJECTS=0` and redeploy. If exact matches at 0.7 stamp badly, raise `VISION_EXACT_MIN_CONFIDENCE`.
