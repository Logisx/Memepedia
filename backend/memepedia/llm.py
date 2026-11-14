"""Gemini calls for the pipeline: vision labelling, lineage drafting, identity and judging.

Every public function makes exactly one Gemini call with low-temperature, JSON-schema-constrained
output and returns typed objects. This module never touches the database or Context.dev; callers
pass in everything it needs (root list, candidate names, web context).
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from memepedia.config import get_settings
from memepedia.models import DraftChain, DraftLink, DraftNode, Kind, VisionLabel

_TIMEOUT_MS = 60_000
_BACKOFF_SECONDS = 2.0


class LLMError(Exception):
    """Raised when a Gemini call fails after one retry."""


class LLMUnavailable(LLMError):
    """Raised when no Gemini API key is configured."""


@dataclass(frozen=True)
class RootInfo:
    """One format-class root the archive always ends chains at."""

    id: str
    name: str
    summary: str


@dataclass(frozen=True)
class Candidate:
    """One existing archive node the model may reuse instead of inventing a duplicate."""

    id: str
    name: str
    kind: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class PendingItem:
    """One unidentified sighting waiting to be clustered into a new specimen."""

    sighting_id: str
    title: str | None
    author: str | None
    description: str
    structure_class: str | None
    overlaid_text: str | None
    catchphrase: str | None
    subjects: tuple[str, ...]


@dataclass(frozen=True)
class Cluster:
    """A proposed group of pending sightings that are the same new meme."""

    name: str
    kind: Kind
    structure_class: str | None
    summary: str
    latin_name: str | None
    shared: Literal["image", "structure", "phrase"]
    sighting_ids: tuple[str, ...]


class _SameOrNewResponse(BaseModel):
    same_as_id: str | None


class _QuoteIndexResponse(BaseModel):
    index: int | None


class _ClusterItem(BaseModel):
    name: str
    kind: Kind
    structure_class: str | None
    summary: str
    latin_name: str | None
    shared: Literal["image", "structure", "phrase"]
    sighting_ids: list[str]


class _ClusterResponse(BaseModel):
    clusters: list[_ClusterItem]


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """Returns the shared Gemini client, building it once from the configured API key."""
    global _client
    if _client is not None:
        return _client
    settings = get_settings()
    if not settings.gemini_key:
        raise LLMUnavailable("no Gemini API key configured (GEMINI_API_KEY)")
    _client = genai.Client(api_key=settings.gemini_key)
    return _client


def _generate(
    contents: str | list[str | types.Part],
    *,
    response_schema: type[BaseModel],
    temperature: float,
) -> str:
    """Makes one Gemini call with structured JSON output, retrying once on a transient failure."""
    client = _get_client()
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=response_schema,
        temperature=temperature,
        http_options=types.HttpOptions(timeout=_TIMEOUT_MS),
    )
    model = get_settings().gemini_model
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = client.models.generate_content(model=model, contents=contents, config=config)
        except errors.ServerError as exc:
            last_error = exc
        except errors.ClientError as exc:
            if exc.code == 429:
                last_error = exc
            else:
                raise LLMError(f"Gemini client error: {exc}") from exc
        except TimeoutError as exc:
            last_error = exc
        else:
            if response.text is None:
                raise LLMError("Gemini returned no text (likely blocked by safety filters)")
            return response.text
        if attempt == 0:
            time.sleep(_BACKOFF_SECONDS)
    raise LLMError(f"Gemini request failed after retry: {last_error}") from last_error


def _format_roots(roots: Sequence[RootInfo]) -> str:
    return "\n".join(f"- {r.id} ({r.name}): {r.summary}" for r in roots)


def _format_candidates(candidates: Sequence[Candidate]) -> str:
    if not candidates:
        return "(none)"
    lines = []
    for c in candidates:
        aliases = f", aliases: {', '.join(c.aliases)}" if c.aliases else ""
        lines.append(f"- id={c.id} name={c.name!r} kind={c.kind}{aliases}")
    return "\n".join(lines)


_VISION_PROMPT = """You label one meme image with structure, not prose, for a meme genealogy
archive. Return is_meme=false for a plain photo, a screenshot of text, news, or non-meme art.
template_guess is the single most widely used name of the meme template or character used in the
image; return null when the image is not a recognisable, established format. When one of the
known names below fits, you MUST return that exact name verbatim (do not paraphrase it).
confidence is your 0 to 1 confidence in template_guess specifically; be conservative — an
unstamped sighting is better than a wrongly stamped one. structure_class must be exactly one of
the given root ids, or null if none fits. overlaid_text is the text written on the image, verbatim
and trimmed (null if none). catchphrase is the reusable spoken phrase if this meme is phrase-driven
(null otherwise). subjects lists the depicted characters, people or things. description is one
neutral sentence describing the reusable visual STRUCTURE of the image (not this post's specific
joke) — it is used as a search query and to group unidentified memes.

Format-class roots:
{roots}

Known template/character names (return one of these verbatim when it fits):
{known_names}

Post title: {title}
"""


def vision_label(
    image: bytes,
    mime_type: str,
    *,
    title: str | None,
    roots: Sequence[RootInfo],
    known_names: Sequence[str] = (),
) -> VisionLabel:
    """Labels one meme image with structure via a single Gemini vision call."""
    prompt = _VISION_PROMPT.format(
        roots=_format_roots(roots),
        known_names=", ".join(known_names) if known_names else "(none)",
        title=title or "(no title)",
    )
    image_part = types.Part.from_bytes(data=image, mime_type=mime_type)
    text = _generate([prompt, image_part], response_schema=VisionLabel, temperature=0.1)
    raw = cast(dict[str, Any], json.loads(text))
    return _parse_vision_label(raw, roots)


def _parse_vision_label(raw: dict[str, Any], roots: Sequence[RootInfo]) -> VisionLabel:
    """Converts the raw JSON response into a VisionLabel, clamping and validating fields."""
    root_ids = {r.id for r in roots}
    structure_class = raw.get("structure_class")
    if structure_class not in root_ids:
        structure_class = None
    confidence = max(0.0, min(1.0, float(raw.get("confidence") or 0.0)))
    return VisionLabel(
        is_meme=bool(raw.get("is_meme", False)),
        template_guess=raw.get("template_guess") or None,
        confidence=confidence,
        structure_class=structure_class,
        subjects=[str(s) for s in (raw.get("subjects") or [])],
        overlaid_text=raw.get("overlaid_text") or None,
        catchphrase=raw.get("catchphrase") or None,
        description=str(raw.get("description") or ""),
    )


_DRAFT_CHAIN_PROMPT = """You draft a hypothesised lineage for one meme, to be verified against the
web afterwards. A node is a meme FORMAT (a character, a template, or a phrase) — never a single
post. Draft the subject and its ancestors up to one of the given roots.

Rules:
- Two axes of descent: the character axis says WHO a meme is about (e.g. Swole Doge descends from
  Doge); the format axis says HOW it is built (e.g. Swole Doge vs. Cheems uses the Virgin vs. Chad
  format). A node has at most one parent per axis.
- A character or its variant climbs the character axis until a root (e.g. Wojak -> drawn-character).
  A pure template has no character parent and climbs the format axis to a root.
- Every chain must end at one of the given roots: include the root as a node with existing_id set
  to the root's id and name equal to the root's name exactly.
- Reuse an existing candidate whenever it is the same meme: set existing_id to the candidate's id
  and name to the candidate's name exactly, instead of inventing a near-duplicate node.
- Keep chains short and real: no invented intermediate ancestors, at most about five hops.
- A parent must never be younger than its child (first_seen date).
- For each NEW node (existing_id null): name is the most widely used name; aliases are other names
  it goes by; first_seen is an ISO date (year precision -> Jan 1, month precision -> day 1; use
  null for both first_seen and date_precision when genuinely unsure, never guess); summary is one
  neutral sentence in your own words; latin_name is a mock-Latin museum binomial or trinomial — a
  variant keeps its parent's genus (e.g. Wojak "Wojakus vulgaris" -> Doomer "Wojakus desperatus").
- Set known=false only when you do not recognise the meme AND the given context gives you nothing
  to go on; then return just the subject with your best structural guess and no fabricated
  ancestors — the caller will fetch web context and ask again.
- DraftLink.child and .parent must each be a name that appears in `nodes`.

Existing archive candidates you may reuse:
{candidates}

Format-class roots (every chain must end at one of these):
{roots}

Query (a meme name or a visual description): {query}

Web context about the query (may be empty):
{context}
"""


def draft_chain(
    query: str,
    *,
    context: str | None,
    candidates: Sequence[Candidate],
    roots: Sequence[RootInfo],
) -> DraftChain:
    """Drafts a hypothesised lineage for one meme, to be verified against the web afterwards."""
    prompt = _DRAFT_CHAIN_PROMPT.format(
        candidates=_format_candidates(candidates),
        roots=_format_roots(roots),
        query=query,
        context=context or "(none)",
    )
    text = _generate(prompt, response_schema=DraftChain, temperature=0.2)
    raw = cast(dict[str, Any], json.loads(text))
    return _parse_draft_chain(raw)


def _parse_draft_node(raw: dict[str, Any]) -> DraftNode:
    return DraftNode(
        existing_id=raw.get("existing_id"),
        name=str(raw["name"]),
        aliases=[str(a) for a in (raw.get("aliases") or [])],
        kind=raw["kind"],
        first_seen=raw.get("first_seen"),
        date_precision=raw.get("date_precision"),
        summary=raw.get("summary"),
        latin_name=raw.get("latin_name"),
    )


def _parse_draft_chain(raw: dict[str, Any]) -> DraftChain:
    """Converts the raw JSON response into a DraftChain, dropping links to unknown node names."""
    nodes = [_parse_draft_node(n) for n in raw.get("nodes", [])]
    names = {n.name for n in nodes}
    links = [
        DraftLink(child=str(link["child"]), parent=str(link["parent"]), axis=link["axis"])
        for link in raw.get("links", [])
        if link.get("child") in names and link.get("parent") in names
    ]
    return DraftChain(
        subject=str(raw.get("subject") or ""),
        known=bool(raw.get("known", False)),
        nodes=nodes,
        links=links,
    )


_SAME_OR_NEW_PROMPT = """Is the meme named below the SAME meme as one of these existing archive
candidates, or is it new? Treat a name and one of a candidate's aliases as the same meme (for
example "Doomer", "Doomer Wojak" and "Wojak (Doomer)" are the same). A variant is NOT the same as
its parent (for example "Doomer" and "Doomer Girl" are different memes). Return the matching
candidate's id, or null if none of them is the same meme.

Candidates:
{candidates}

Name: {name}
Descriptive hint (may be empty): {hint}
"""


def same_or_new(name: str, *, hint: str | None, candidates: Sequence[Candidate]) -> str | None:
    """Checks whether `name` is the same meme as one of `candidates`, for the resolver."""
    prompt = _SAME_OR_NEW_PROMPT.format(
        candidates=_format_candidates(candidates), name=name, hint=hint or "(none)"
    )
    text = _generate(prompt, response_schema=_SameOrNewResponse, temperature=0.0)
    raw = cast(dict[str, Any], json.loads(text))
    candidate_ids = {c.id for c in candidates}
    return _parse_same_or_new(raw, candidate_ids)


def _parse_same_or_new(raw: dict[str, Any], candidate_ids: set[str]) -> str | None:
    same_as = raw.get("same_as_id")
    return same_as if same_as in candidate_ids else None


_PICK_QUOTE_PROMPT = """A claim about meme lineage is below, followed by numbered sentences copied
verbatim from web pages. Return the index of the single sentence that best supports the claim, or
null if none really does. A sentence that merely lists both names without saying one derives from
or is a variant of the other does NOT support the claim.

Claim: {claim}

Sentences:
{sentences}
"""


def pick_quote(claim: str, sentences: Sequence[str]) -> int | None:
    """Picks the index of the sentence that best supports a lineage claim, or None."""
    numbered = "\n".join(f"{i}: {s}" for i, s in enumerate(sentences))
    prompt = _PICK_QUOTE_PROMPT.format(claim=claim, sentences=numbered or "(none)")
    text = _generate(prompt, response_schema=_QuoteIndexResponse, temperature=0.0)
    raw = cast(dict[str, Any], json.loads(text))
    return _clamp_quote_index(raw.get("index"), len(sentences))


def _clamp_quote_index(index: Any, count: int) -> int | None:
    if not isinstance(index, int) or isinstance(index, bool):
        return None
    if index < 0 or index >= count:
        return None
    return index


_CLUSTER_PROMPT = """These are unidentified meme sightings from the last 72 hours. Group the ones
that are the SAME new meme (not yet in the archive) into clusters. You may leave items ungrouped —
do not force unrelated posts together. `shared` says what ties a cluster together: the same image
("image"), the same visual structure/template ("structure"), or the same spoken phrase ("phrase").
Give each cluster a name, kind, your best structure_class (a root id, or null), a one-sentence
neutral summary, and a mock-Latin latin_name. Numeric thresholds (sighting and author counts) are
checked separately by the caller — just propose honest groupings.

Pending sightings:
{items}
"""


def _format_pending_items(items: Sequence[PendingItem]) -> str:
    lines = []
    for item in items:
        lines.append(
            f"- id={item.sighting_id} title={item.title!r} author={item.author!r} "
            f"structure_class={item.structure_class!r} overlaid_text={item.overlaid_text!r} "
            f"catchphrase={item.catchphrase!r} subjects={list(item.subjects)} "
            f"description={item.description!r}"
        )
    return "\n".join(lines)


def cluster_pending(items: Sequence[PendingItem]) -> list[Cluster]:
    """Groups unidentified sightings that look like the same new meme."""
    if not items:
        return []
    prompt = _CLUSTER_PROMPT.format(items=_format_pending_items(items))
    text = _generate(prompt, response_schema=_ClusterResponse, temperature=0.2)
    raw = cast(dict[str, Any], json.loads(text))
    valid_ids = {item.sighting_id for item in items}
    return _parse_clusters(raw, valid_ids)


def _parse_clusters(raw: dict[str, Any], valid_ids: set[str]) -> list[Cluster]:
    """Converts the raw JSON response into Clusters, dropping unknown sighting ids and empties."""
    clusters: list[Cluster] = []
    for c in raw.get("clusters", []):
        ids = tuple(i for i in (c.get("sighting_ids") or []) if i in valid_ids)
        if not ids:
            continue
        clusters.append(
            Cluster(
                name=str(c["name"]),
                kind=c["kind"],
                structure_class=c.get("structure_class"),
                summary=str(c.get("summary") or ""),
                latin_name=c.get("latin_name"),
                shared=c["shared"],
                sighting_ids=ids,
            )
        )
    return clusters
