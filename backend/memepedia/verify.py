"""Fact-checking: find a sentence on the open web that supports one lineage link, verbatim.

Pure text functions do no network I/O and are unit-tested directly. `find_evidence` and
`evidence_in_page` call out to Context.dev and the LLM; any failure there is logged and
turned into `None` so a failed check never crashes a trace.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence

from memepedia import blocklist, contextdev, llm
from memepedia.contextdev import ContextDevError
from memepedia.llm import LLMError
from memepedia.models import Axis, Evidence, MemeNode

logger = logging.getLogger("memepedia.verify")

_MIN_SENTENCE_LEN = 40
_MAX_SENTENCE_LEN = 400
_MAX_CANDIDATES = 12
_MAX_PER_PAGE = 4

_HEADING_RE = re.compile(r"^\s*#{1,6}\s*")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_FOOTNOTE_ANCHOR = r"(?:cite_note|cite_ref|ref|fn|footnote)-"
_FOOTNOTE_LINK_RE = re.compile(r"\[\\?\[?\d{1,3}\\?\]?\]\([^)]*" + _FOOTNOTE_ANCHOR + r"[^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_EMPHASIS_RE = re.compile(r"(\*{1,3}|_{1,3}|`)")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_FRONT_MATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*\|?\s*$")

_ABBREVIATIONS = (
    "vs.",
    "e.g.",
    "i.e.",
    "mr.",
    "mrs.",
    "ms.",
    "dr.",
    "jr.",
    "sr.",
    "st.",
    "etc.",
    "no.",
    "vol.",
    "approx.",
    "ca.",
    "u.s.",
    "u.k.",
    "prof.",
)


def clean_text(markdown: str) -> str:
    """The page as plain text: drop images, link targets, heading/emphasis marks, HTML, tables."""
    text = _FRONT_MATTER_RE.sub("", markdown)
    text = _IMAGE_RE.sub("", text)
    text = _FOOTNOTE_LINK_RE.sub("", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _HTML_TAG_RE.sub("", text)
    lines = []
    for raw_line in text.split("\n"):
        if _TABLE_SEP_RE.match(raw_line):
            continue
        line = _HEADING_RE.sub("", raw_line)
        line = _EMPHASIS_RE.sub("", line)
        line = line.replace("|", " ").strip()
        lines.append(line)
    return "\n".join(lines)


def _ends_with_abbreviation(line: str, end: int) -> bool:
    chunk = line[max(0, end - 10) : end].lower()
    return any(chunk.endswith(abbr) for abbr in _ABBREVIATIONS)


def _split_line(line: str) -> list[str]:
    parts: list[str] = []
    start = 0
    n = len(line)
    for i, ch in enumerate(line):
        if ch not in ".!?":
            continue
        at_boundary = i + 1 >= n or line[i + 1].isspace()
        if not at_boundary or _ends_with_abbreviation(line, i + 1):
            continue
        parts.append(line[start : i + 1])
        start = i + 1
    if start < n:
        parts.append(line[start:])
    return parts


def split_sentences(text: str) -> list[str]:
    """Sentences as exact slices of `text`; a heading line never glues onto the next sentence."""
    sentences: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        for sentence in _split_line(stripped):
            sentence = sentence.strip()
            if _MIN_SENTENCE_LEN <= len(sentence) <= _MAX_SENTENCE_LEN:
                sentences.append(sentence)
    return sentences


def mentions(sentence: str, names: Sequence[str]) -> bool:
    """Case-insensitive whole-word/phrase match of any of `names` in `sentence`."""
    for name in names:
        name = name.strip()
        if not name:
            continue
        pattern = r"(?<!\w)" + re.escape(name) + r"(?!\w)"
        if re.search(pattern, sentence, re.IGNORECASE):
            return True
    return False


def _overlap_score(sentence: str, words: Sequence[str]) -> int:
    low = sentence.lower()
    return sum(1 for word in words if word and word.lower() in low)


def candidate_sentences(
    text: str,
    child_names: Sequence[str],
    parent_names: Sequence[str] | None,
    limit: int,
    root_words: Sequence[str] = (),
) -> list[str]:
    """Sentences mentioning the child, and the parent when named; best-first by root overlap."""
    sentences = [s for s in split_sentences(text) if mentions(s, child_names)]
    if parent_names is not None:
        sentences = [s for s in sentences if mentions(s, parent_names)]
        return sentences[:limit]
    ranked = sorted(sentences, key=lambda s: _overlap_score(s, root_words), reverse=True)
    return ranked[:limit]


def claim(child: MemeNode, parent: MemeNode, axis: Axis) -> str:
    """The statement a quote must support for this link."""
    if parent.kind == "format_class":
        summary = parent.summary or ""
        return f"{child.name} is a {parent.name.lower()}: {summary}".strip()
    if axis == "character":
        return f"{child.name} is a variant of, or derives from, {parent.name}."
    return f"{child.name} uses or derives from the {parent.name} format."


def _root_words(parent: MemeNode) -> list[str]:
    words = parent.name.split()
    if parent.summary:
        words += parent.summary.split()
    return words


def evidence_in_page(
    child: MemeNode, parent: MemeNode, axis: Axis, *, markdown: str, url: str, title: str
) -> Evidence | None:
    """One page's candidates, judged by the LLM, turned into `Evidence`, or `None`."""
    if blocklist.is_blocked(url, title):
        return None
    cleaned = clean_text(markdown)
    child_names = [child.name, *child.aliases]
    parent_names = None if parent.kind == "format_class" else [parent.name, *parent.aliases]
    candidates = candidate_sentences(
        cleaned, child_names, parent_names, _MAX_PER_PAGE, root_words=_root_words(parent)
    )
    if not candidates:
        return None
    try:
        index = llm.pick_quote(claim(child, parent, axis), candidates)
    except LLMError:
        logger.exception("pick_quote failed for %s -> %s", child.id, parent.id)
        return None
    if index is None:
        return None
    quote = candidates[index]
    assert quote in cleaned
    if blocklist.is_blocked(quote):
        return None
    return Evidence(quote=quote, source_url=url, source_title=title or url)


def _search_query(child: MemeNode, parent: MemeNode, *, quoted: bool) -> str:
    if parent.kind == "format_class":
        return f'"{child.name}" meme origin' if quoted else f"{child.name} meme origin"
    if quoted:
        return f'"{child.name}" "{parent.name}" meme'
    return f"{child.name} {parent.name} meme"


def _gather_candidates(
    hits: Sequence[contextdev.SearchHit],
    child_names: Sequence[str],
    parent_names: Sequence[str] | None,
    root_words: Sequence[str],
) -> list[tuple[str, str, str]]:
    """(sentence, page_cleaned_text, url) triples across hits, capped overall and per page."""
    found: list[tuple[str, str, str]] = []
    for hit in hits:
        if blocklist.is_blocked(hit.url, hit.title) or not hit.markdown:
            continue
        cleaned = clean_text(hit.markdown)
        for sentence in candidate_sentences(
            cleaned, child_names, parent_names, _MAX_PER_PAGE, root_words=root_words
        ):
            found.append((sentence, cleaned, hit.url))
            if len(found) >= _MAX_CANDIDATES:
                return found
    return found


def find_evidence(child: MemeNode, parent: MemeNode, axis: Axis) -> Evidence | None:
    """Search the web for a verbatim quote supporting one link, or `None` if none is found."""
    child_names = [child.name, *child.aliases]
    parent_names = None if parent.kind == "format_class" else [parent.name, *parent.aliases]
    root_words = _root_words(parent)
    try:
        hits = contextdev.search(_search_query(child, parent, quoted=True), label="verify")
        found = _gather_candidates(hits, child_names, parent_names, root_words)
        if not found:
            hits = contextdev.search(_search_query(child, parent, quoted=False), label="verify")
            found = _gather_candidates(hits, child_names, parent_names, root_words)
    except ContextDevError:
        logger.exception("search failed for %s -> %s", child.id, parent.id)
        return None
    if not found:
        return None
    titles_by_url = {hit.url: (hit.title or hit.url) for hit in hits}
    sentences = [f[0] for f in found]
    try:
        index = llm.pick_quote(claim(child, parent, axis), sentences)
    except LLMError:
        logger.exception("pick_quote failed for %s -> %s", child.id, parent.id)
        return None
    if index is None:
        return None
    quote, cleaned, url = found[index]
    assert quote in cleaned
    title = titles_by_url.get(url, url)
    if blocklist.is_blocked(quote, url, title):
        return None
    return Evidence(quote=quote, source_url=url, source_title=title)
