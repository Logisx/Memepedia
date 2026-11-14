"""Social sources. Every fetcher returns the same Post shape, so losing one touches nothing else."""

from __future__ import annotations

from dataclasses import dataclass

from memepedia.models import Platform, Post


@dataclass(frozen=True)
class Feed:
    """One watched feed: a Lemmy community, a subreddit or an Imgflip stream."""

    key: str
    platform: Platform
    target: str


class SourceError(Exception):
    """One feed is blocked or unreachable; callers should skip it, not fail the whole tick."""


FEEDS: list[Feed] = [
    Feed("lemmy:lemmy.world/memes", "lemmy", "lemmy.world/memes"),
    Feed("lemmy:lemmy.ml/memes", "lemmy", "lemmy.ml/memes"),
    Feed("lemmy:lemmy.world/lemmyshitpost", "lemmy", "lemmy.world/lemmyshitpost"),
    Feed("lemmy:midwest.social/memes", "lemmy", "midwest.social/memes"),
    Feed("lemmy:lemmy.dbzer0.com/memes", "lemmy", "lemmy.dbzer0.com/memes"),
    Feed("lemmy:lemmy.blahaj.zone/196", "lemmy", "lemmy.blahaj.zone/196"),
    Feed("lemmy:lemmy.world/programmerhumor", "lemmy", "lemmy.world/programmerhumor"),
    Feed("lemmy:sopuli.xyz/memes", "lemmy", "sopuli.xyz/memes"),
    Feed("lemmy:lemmy.world/196", "lemmy", "lemmy.world/196"),
    Feed("reddit:memes", "reddit", "memes"),
    Feed("reddit:dankmemes", "reddit", "dankmemes"),
    Feed("reddit:me_irl", "reddit", "me_irl"),
    Feed("reddit:MemeEconomy", "reddit", "MemeEconomy"),
    Feed("reddit:ProgrammerHumor", "reddit", "ProgrammerHumor"),
    Feed("imgflip:fun", "imgflip", "fun"),
    Feed("imgflip:memes", "imgflip", "memes"),
]


def fetch(feed: Feed) -> list[Post]:
    """Fetch one feed's current posts, dispatching on its platform."""
    if feed.platform == "lemmy":
        from memepedia.sources.lemmy import fetch_lemmy

        return fetch_lemmy(feed)
    if feed.platform == "reddit":
        from memepedia.sources.reddit import fetch_reddit

        return fetch_reddit(feed)
    if feed.platform == "imgflip":
        from memepedia.sources.imgflip import fetch_imgflip

        return fetch_imgflip(feed)
    raise SourceError(f"no fetcher for platform {feed.platform!r}")
