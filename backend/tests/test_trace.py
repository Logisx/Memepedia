"""Tests for memepedia.trace against the real test database, with network calls monkeypatched."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest

from memepedia import db, images, llm, resolver, store, trace, verify
from memepedia.contextdev import ScrapeResult
from memepedia.llm import LLMError
from memepedia.models import (
    DatePrecision,
    DraftChain,
    DraftLink,
    DraftNode,
    Evidence,
    Kind,
    Link,
    MemeNode,
    NodeStatus,
)


@pytest.fixture(scope="module", autouse=True)
def _db() -> None:
    db.configure(db.local_url("memepedia_test"))
    db.init_schema()


@pytest.fixture
def cleanup() -> Iterator[list[str]]:
    ids: list[str] = []
    yield ids
    if ids:
        db.execute("DELETE FROM nodes WHERE id = ANY(%s)", (ids,))


def _node(
    id_: str,
    name: str,
    *,
    kind: Kind = "character",
    first_seen: date | None = None,
    date_precision: DatePrecision | None = None,
    status: NodeStatus = "established",
) -> MemeNode:
    return MemeNode(
        id=id_,
        name=name,
        aliases=[],
        kind=kind,
        latin_name=None,
        image_url=None,
        image_credit_url=None,
        first_seen=first_seen,
        date_precision=date_precision,
        summary="a test node",
        status=status,
        sightings_24h=0,
        sightings_7d=0,
    )


def _make(cleanup: list[str], node: MemeNode) -> MemeNode:
    store.upsert_node(node)
    cleanup.append(node.id)
    return node


def _draft_node(
    name: str, *, existing_id: str | None = None, kind: Kind = "character"
) -> DraftNode:
    return DraftNode(
        existing_id=existing_id,
        name=name,
        aliases=[],
        kind=kind,
        first_seen=None,
        date_precision=None,
        summary="a drafted node",
        latin_name=None,
    )


# --- materialise -------------------------------------------------------------------------------


def test_materialise_builds_new_node_and_links_to_root(
    monkeypatch: pytest.MonkeyPatch, cleanup: list[str]
) -> None:
    root = _make(cleanup, _node("t-root-a", "Test Root A", kind="format_class"))
    draft = DraftChain(
        subject="Grug Test",
        known=True,
        nodes=[
            _draft_node("Grug Test"),
            _draft_node(root.name, existing_id=root.id, kind="format_class"),
        ],
        links=[DraftLink(child="Grug Test", parent=root.name, axis="character")],
    )
    subject_id = trace.materialise(draft)
    assert subject_id is not None
    cleanup.append(subject_id)
    link = store.get_link(subject_id, "character")
    assert link is not None
    assert link.parent_id == root.id
    assert link.status == "inferred"


def test_materialise_resolves_duplicate_instead_of_creating(
    monkeypatch: pytest.MonkeyPatch, cleanup: list[str]
) -> None:
    existing = _make(cleanup, _node("t-doomer-a", "Doomer Test A"))
    root = _make(cleanup, _node("t-root-b", "Test Root B", kind="format_class"))

    def fake_resolve(name: str, *, hint: str | None = None, allow_llm: bool = True) -> str | None:
        return existing.id if name == "Doomer Test A Wojak" else None

    monkeypatch.setattr(resolver, "resolve", fake_resolve)
    draft = DraftChain(
        subject="Doomer Test A Wojak",
        known=True,
        nodes=[
            _draft_node("Doomer Test A Wojak"),
            _draft_node(root.name, existing_id=root.id, kind="format_class"),
        ],
        links=[DraftLink(child="Doomer Test A Wojak", parent=root.name, axis="character")],
    )
    subject_id = trace.materialise(draft)
    assert subject_id == existing.id
    assert store.get_node("doomer-test-a-wojak") is None


def test_materialise_never_overwrites_an_existing_cited_link(cleanup: list[str]) -> None:
    parent1 = _make(cleanup, _node("t-parent-1", "Test Parent One"))
    parent2 = _make(cleanup, _node("t-parent-2", "Test Parent Two"))
    child = _make(cleanup, _node("t-child-1", "Test Child One"))
    store.upsert_link(
        Link(
            child_id=child.id,
            parent_id=parent1.id,
            axis="character",
            status="cited",
            quote="Test Child One descends from Test Parent One.",
            source_url="https://example.com/a",
            source_title="A",
        )
    )
    draft = DraftChain(
        subject=child.name,
        known=True,
        nodes=[
            _draft_node(child.name, existing_id=child.id),
            _draft_node(parent2.name, existing_id=parent2.id),
        ],
        links=[DraftLink(child=child.name, parent=parent2.name, axis="character")],
    )
    trace.materialise(draft)
    link = store.get_link(child.id, "character")
    assert link is not None
    assert link.parent_id == parent1.id
    assert link.status == "cited"


def test_materialise_rejects_a_cycle(cleanup: list[str]) -> None:
    y = _make(cleanup, _node("t-cycle-y", "Test Cycle Y"))
    x = _make(cleanup, _node("t-cycle-x", "Test Cycle X"))
    store.upsert_link(
        Link(
            child_id=x.id,
            parent_id=y.id,
            axis="character",
            status="inferred",
            quote=None,
            source_url=None,
            source_title=None,
        )
    )
    draft = DraftChain(
        subject=y.name,
        known=True,
        nodes=[_draft_node(y.name, existing_id=y.id), _draft_node(x.name, existing_id=x.id)],
        links=[DraftLink(child=y.name, parent=x.name, axis="character")],
    )
    trace.materialise(draft)
    assert store.get_link(y.id, "character") is None


def test_materialise_rejects_a_younger_parent(cleanup: list[str]) -> None:
    child = _make(
        cleanup,
        _node("t-young-c", "Test Young Child", first_seen=date(2010, 1, 1), date_precision="year"),
    )
    parent = _make(
        cleanup,
        _node("t-young-p", "Test Young Parent", first_seen=date(2020, 1, 1), date_precision="year"),
    )
    draft = DraftChain(
        subject=child.name,
        known=True,
        nodes=[
            _draft_node(child.name, existing_id=child.id),
            _draft_node(parent.name, existing_id=parent.id),
        ],
        links=[DraftLink(child=child.name, parent=parent.name, axis="character")],
    )
    trace.materialise(draft)
    assert store.get_link(child.id, "character") is None


def test_materialise_attaches_rootless_chain_to_named_root(cleanup: list[str]) -> None:
    root = _make(cleanup, _node("t-root-c", "Test Root C", kind="format_class"))
    draft = DraftChain(
        subject="Template Test",
        known=True,
        nodes=[
            _draft_node("Template Test", kind="template"),
            _draft_node(root.name, existing_id=root.id, kind="format_class"),
        ],
        links=[],
    )
    subject_id = trace.materialise(draft)
    assert subject_id is not None
    cleanup.append(subject_id)
    link = store.get_link(subject_id, "format")
    assert link is not None
    assert link.parent_id == root.id


def test_materialise_sets_specimen_status_and_todays_date(cleanup: list[str]) -> None:
    root = _make(cleanup, _node("t-root-d", "Test Root D", kind="format_class"))
    draft = DraftChain(
        subject="New Specimen Test",
        known=True,
        nodes=[
            _draft_node("New Specimen Test"),
            _draft_node(root.name, existing_id=root.id, kind="format_class"),
        ],
        links=[DraftLink(child="New Specimen Test", parent=root.name, axis="character")],
    )
    subject_id = trace.materialise(draft, as_specimen=True)
    assert subject_id is not None
    cleanup.append(subject_id)
    node = store.get_node(subject_id)
    assert node is not None
    assert node.status == "specimen"
    assert node.first_seen == date.today()


# --- trace() -------------------------------------------------------------------------------------


def test_trace_new_meme_event_order(monkeypatch: pytest.MonkeyPatch, cleanup: list[str]) -> None:
    root = _make(cleanup, _node("t-root-e", "Test Root E", kind="format_class"))
    draft = DraftChain(
        subject="Grug Chain Test",
        known=True,
        nodes=[
            _draft_node("Grug Chain Test"),
            _draft_node(root.name, existing_id=root.id, kind="format_class"),
        ],
        links=[DraftLink(child="Grug Chain Test", parent=root.name, axis="character")],
    )
    monkeypatch.setattr(llm, "draft_chain", lambda *a, **kw: draft)
    monkeypatch.setattr(images, "find_image", lambda *a, **kw: None)
    monkeypatch.setattr(
        verify,
        "find_evidence",
        lambda *a, **kw: Evidence(
            quote="Grug Chain Test derives from Test Root E.",
            source_url="https://example.com/grug",
            source_title="Grug",
        ),
    )
    events = list(trace.trace("Grug Chain Test"))
    cleanup.append("grug-chain-test")
    types = [e.type for e in events]
    assert types == ["status", "status", "chain", "link", "done"]
    assert events[-1].node_id == "grug-chain-test"  # type: ignore[union-attr]


def test_trace_existing_meme_short_circuits(
    monkeypatch: pytest.MonkeyPatch, cleanup: list[str]
) -> None:
    node = _make(cleanup, _node("t-existing-a", "Test Existing Meme"))

    def fail_if_called(*a: Any, **kw: Any) -> DraftChain:
        raise AssertionError("draft_chain should not be called for a known meme")

    monkeypatch.setattr(llm, "draft_chain", fail_if_called)
    events = list(trace.trace(node.name))
    types = [e.type for e in events]
    assert types == ["status", "chain", "done"]
    assert events[-1].node_id == node.id  # type: ignore[union-attr]


def test_trace_failure_yields_exactly_one_error_event(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **kw: Any) -> DraftChain:
        raise LLMError("boom")

    monkeypatch.setattr(llm, "draft_chain", boom)
    events = list(trace.trace("A Totally Unknown Meme Name Xyzzy"))
    errors = [e for e in events if e.type == "error"]
    assert len(errors) == 1
    assert events[-1].type == "error"


# --- propose ---------------------------------------------------------------------------------


def test_propose_accepted(monkeypatch: pytest.MonkeyPatch, cleanup: list[str]) -> None:
    parent = _make(cleanup, _node("t-prop-parent", "Test Propose Parent"))
    child = _make(cleanup, _node("t-prop-child", "Test Propose Child"))
    store.upsert_link(
        Link(
            child_id=child.id,
            parent_id=parent.id,
            axis="character",
            status="inferred",
            quote=None,
            source_url=None,
            source_title=None,
        )
    )
    markdown = "Test Propose Child is a variant of, or derives from, Test Propose Parent, say fans."
    monkeypatch.setattr(
        "memepedia.contextdev.scrape",
        lambda *a, **kw: ScrapeResult(
            url="https://example.com/proposed",
            title="Proposed",
            markdown=markdown,
            html=None,
            images=[],
            credits=1.0,
        ),
    )
    monkeypatch.setattr(llm, "pick_quote", lambda claim, sentences: 0)
    response = trace.propose(child.id, "https://example.com/proposed", "found it here")
    assert response.accepted is True
    assert response.link is not None
    assert response.link.status == "cited"
    link = store.get_link(child.id, "character")
    assert link is not None and link.status == "cited"


def test_propose_rejected_when_no_qualifying_sentence(
    monkeypatch: pytest.MonkeyPatch, cleanup: list[str]
) -> None:
    parent = _make(cleanup, _node("t-prop-parent-2", "Test Propose Parent Two"))
    child = _make(cleanup, _node("t-prop-child-2", "Test Propose Child Two"))
    store.upsert_link(
        Link(
            child_id=child.id,
            parent_id=parent.id,
            axis="character",
            status="inferred",
            quote=None,
            source_url=None,
            source_title=None,
        )
    )
    monkeypatch.setattr(
        "memepedia.contextdev.scrape",
        lambda *a, **kw: ScrapeResult(
            url="https://example.com/unrelated",
            title="Unrelated",
            markdown="Totally off topic text.",
            html=None,
            images=[],
            credits=1.0,
        ),
    )
    response = trace.propose(child.id, "https://example.com/unrelated", "")
    assert response.accepted is False
    assert response.link is None


def test_propose_rejects_knowyourmeme_url(cleanup: list[str]) -> None:
    node = _make(cleanup, _node("t-prop-kym", "Test Propose KYM"))
    response = trace.propose(node.id, "https://knowyourmeme.com/memes/whatever", "")
    assert response.accepted is False
    assert response.link is None


def test_propose_reports_no_inferred_links(
    monkeypatch: pytest.MonkeyPatch, cleanup: list[str]
) -> None:
    node = _make(cleanup, _node("t-prop-none", "Test Propose No Links"))
    monkeypatch.setattr(
        "memepedia.contextdev.scrape",
        lambda *a, **kw: ScrapeResult(
            url="https://example.com/x",
            title="X",
            markdown="Some unrelated text here.",
            html=None,
            images=[],
            credits=1.0,
        ),
    )
    response = trace.propose(node.id, "https://example.com/x", "")
    assert response.accepted is False
    assert response.link is None


def test_propose_unknown_node_raises_lookup_error() -> None:
    with pytest.raises(LookupError):
        trace.propose("no-such-node-id", "https://example.com/x", "")
