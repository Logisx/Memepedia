"""No-network tests for memepedia.blocklist, the shared blocked-source predicate."""

from __future__ import annotations

from memepedia import blocklist


def test_is_blocked_true_for_direct_domain() -> None:
    assert blocklist.is_blocked("https://knowyourmeme.com/memes/doomer")


def test_is_blocked_true_for_www_and_mixed_case() -> None:
    assert blocklist.is_blocked("https://WWW.KnowYourMeme.com/memes/doomer")


def test_is_blocked_true_for_cdn_domain() -> None:
    assert blocklist.is_blocked("https://i.kym-cdn.com/photos/images/x.jpg")


def test_is_blocked_true_when_mentioned_in_title_not_url() -> None:
    assert blocklist.is_blocked(
        "https://www.reddit.com/r/KnowYourMeme/comments/1f89lij/x/",
        "r/KnowYourMeme on Reddit: What Is The 'Awkward Look Monkey Puppet' Meme?",
    )


def test_is_blocked_false_for_unrelated_text() -> None:
    assert not blocklist.is_blocked("https://en.wikipedia.org/wiki/Doomer", "Doomer - Wikipedia")


def test_is_blocked_ignores_none_parts() -> None:
    assert not blocklist.is_blocked(None, "https://example.com", None)
