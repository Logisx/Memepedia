"""The duplicate rule (memepedia.dedupe). Pure: no network, no database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from memepedia import dedupe
from memepedia.dedupe import Candidate

_T0 = datetime(2026, 11, 15, 8, 0, tzinfo=UTC)
_BASE = "0" * 64


def _flip(bits: int) -> str:
    """A fingerprint `bits` bits away from _BASE."""
    return f"{(1 << bits) - 1:064x}"


def _c(
    id: str,
    *,
    url: str | None = None,
    fp: str | None = _BASE,
    author: str | None = "someone",
    title: str = "a joke",
    at: datetime = _T0,
) -> Candidate:
    return Candidate(id, url or f"https://img.test/{id}.jpg", fp, author, title, at)


def test_identical_image_url_is_a_duplicate_whoever_posted_it() -> None:
    a = _c("a", url="https://img.test/same.jpg", author="cm0002", fp=None)
    b = _c("b", url="https://img.test/same.jpg", author="join", fp=None)
    match = dedupe.compare(b, a)
    assert match is not None and match.rule == "D1"


def test_near_identical_pixels_are_a_duplicate_without_any_other_signal() -> None:
    a = _c("a", author="x", title="first")
    b = _c("b", fp=_flip(3), author="y", title="second")
    match = dedupe.compare(b, a)
    assert match is not None and match.rule == "D2" and match.bits == 3


def test_same_author_and_title_with_similar_pixels_is_a_duplicate() -> None:
    a = _c("a", author="G-5-0", title="It had a good run")
    b = _c("b", fp=_flip(8), author="G-5-0", title="It had a good run", at=_T0 + timedelta(hours=2))
    match = dedupe.compare(b, a)
    assert match is not None and match.rule == "D3"


def test_two_me_irl_posts_from_different_authors_are_not_duplicates() -> None:
    a = _c("a", author="alice", title="me_irl")
    b = _c("b", fp=_flip(10), author="bob", title="me_irl")
    assert not dedupe.same_post(a, b)
    assert dedupe.norm_title("me_irl") == ""
    assert dedupe.norm_title("Me IRL") == ""


def test_similar_pixels_with_nothing_else_in_common_are_not_duplicates() -> None:
    a = _c("a", author="alice", title="cat tax")
    b = _c("b", fp=_flip(10), author="bob", title="monday again")
    assert not dedupe.same_post(a, b)


def test_close_pixels_a_month_apart_are_not_duplicates() -> None:
    a = _c("a")
    b = _c("b", fp=_flip(3), at=_T0 + timedelta(days=30))
    assert not dedupe.same_post(a, b)


def test_a_missing_fingerprint_only_ever_matches_by_url() -> None:
    a = _c("a", fp=None)
    b = _c("b", fp=_BASE)
    assert not dedupe.same_post(a, b)
    assert not dedupe.same_post(b, a)


def test_find_original_picks_the_earliest_match_and_never_itself() -> None:
    late = _c("late", fp=_flip(1), at=_T0 + timedelta(hours=3))
    early = _c("early", fp=_flip(2), at=_T0)
    unrelated = _c("other", fp="f" * 64, at=_T0 - timedelta(hours=1))
    me = _c("me", at=_T0 + timedelta(hours=5))
    match = dedupe.find_original(me, [late, me, unrelated, early])
    assert match is not None and match.original.id == "early"
    assert dedupe.find_original(me, [me, unrelated]) is None
