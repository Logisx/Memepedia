"""Tests for memepedia.store against the loaded fixture database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from memepedia import db, store
from memepedia.models import Evidence, MemeNode, Post


def test_search_exact_before_prefix_before_substring(client: TestClient) -> None:
    results = store.search_nodes("doge")
    ids = [n.id for n in results]
    assert ids[0] == "doge"
    assert "swole-doge" in ids
    assert ids.index("doge") < ids.index("swole-doge")


def test_search_matches_alias_case_insensitively(client: TestClient) -> None:
    results = store.search_nodes("CHAD")
    ids = {n.id for n in results}
    assert "yes-chad" in ids


def test_search_blank_query_returns_popular_mix(client: TestClient) -> None:
    results = store.search_nodes("", limit=5)
    assert len(results) == 5
    sevens = [n.sightings_7d for n in results]
    assert sevens == sorted(sevens, reverse=True)


def test_sighting_insert_dedupes_on_post_url(client: TestClient) -> None:
    post = Post(
        platform="lemmy",
        source="test",
        post_url="https://example.test/unique-post-1",
        image_url="https://example.test/img.jpg",
        title="test sighting",
        author="tester",
        posted_at=datetime.now(UTC),
    )
    first_id = store.insert_sighting(post, None, "doomer", "resolved")
    second_id = store.insert_sighting(post, None, "doomer", "resolved")
    assert first_id is not None
    assert second_id is None


def test_add_alias_rejects_duplicate_and_name(client: TestClient) -> None:
    node = store.get_node("doge")
    assert node is not None
    before = len(node.aliases)
    store.add_alias("doge", "kabosu")  # already an alias, case-insensitively
    store.add_alias("doge", "Doge")  # equals the name
    after = store.get_node("doge")
    assert after is not None
    assert len(after.aliases) == before


def test_add_alias_adds_new_alias(client: TestClient) -> None:
    store.upsert_node(
        MemeNode(
            id="alias-test-node",
            name="Alias Test Node",
            aliases=[],
            kind="character",
            latin_name=None,
            image_url=None,
            image_credit_url=None,
            first_seen=None,
            date_precision=None,
            summary=None,
            status="specimen",
            sightings_24h=0,
            sightings_7d=0,
            nsfw=None,
        )
    )
    store.add_alias("alias-test-node", "ATN")
    node = store.get_node("alias-test-node")
    assert node is not None
    assert node.aliases == ["ATN"]


def test_cite_link_flips_status_and_returns_updated_link(client: TestClient) -> None:
    link = store.get_link("bloomer", "character")
    assert link is not None
    assert link.status == "inferred"
    updated = store.cite_link(
        "bloomer",
        "character",
        Evidence(
            quote="Bloomer is the cheerful counterpart to Doomer.",
            source_url="https://example.test/bloomer",
            source_title="Bloomer - Example",
        ),
    )
    assert updated is not None
    assert updated.status == "cited"
    assert updated.quote == "Bloomer is the cheerful counterpart to Doomer."


def test_cite_link_returns_none_for_unknown_link(client: TestClient) -> None:
    evidence = Evidence(quote="x", source_url="https://example.test", source_title="x")
    assert store.cite_link("no-such-node", "character", evidence) is None


def test_rising_maths_only_includes_spiking_nodes(client: TestClient) -> None:
    store.upsert_node(
        MemeNode(
            id="rising-test-node",
            name="Rising Test Node",
            aliases=[],
            kind="character",
            latin_name=None,
            image_url=None,
            image_credit_url=None,
            first_seen=None,
            date_precision=None,
            summary=None,
            status="established",
            sightings_24h=0,
            sightings_7d=0,
            nsfw=None,
        )
    )
    now = datetime.now(UTC)
    for i in range(5):
        post = Post(
            platform="lemmy",
            source="test",
            post_url=f"https://example.test/rising-recent-{i}",
            image_url="https://example.test/img.jpg",
            title="recent",
            author="tester",
            posted_at=now - timedelta(hours=1, minutes=i),
        )
        store.insert_sighting(post, None, "rising-test-node", "resolved", nsfw=False)
    for i in range(6):
        post = Post(
            platform="lemmy",
            source="test",
            post_url=f"https://example.test/rising-prior-{i}",
            image_url="https://example.test/img.jpg",
            title="prior",
            author="tester",
            posted_at=now - timedelta(days=2, hours=i),
        )
        store.insert_sighting(post, None, "rising-test-node", "resolved", nsfw=False)
    rising = {rf.node.id: rf for rf in store.rising(limit=50)}
    assert "rising-test-node" in rising
    entry = rising["rising-test-node"]
    assert entry.count_24h == 5
    assert entry.daily_mean_prior == 1.0


def test_expire_specimens_removes_only_stale_ones(client: TestClient) -> None:
    def specimen(node_id: str) -> MemeNode:
        return MemeNode(
            id=node_id,
            name=node_id,
            aliases=[],
            kind="template",
            latin_name=None,
            image_url=None,
            image_credit_url=None,
            first_seen=None,
            date_precision=None,
            summary=None,
            status="specimen",
            sightings_24h=0,
            sightings_7d=0,
            nsfw=None,
        )

    def post(url: str, age: timedelta) -> Post:
        return Post(
            platform="lemmy",
            source="test",
            post_url=url,
            image_url=url + ".png",
            title="t",
            author="a",
            posted_at=datetime.now(UTC) - age,
        )

    for node_id in ("stale-specimen", "live-specimen", "new-specimen"):
        store.upsert_node(specimen(node_id))
    store.insert_sighting(
        post("https://x.test/stale", timedelta(days=9)), None, "stale-specimen", "resolved"
    )
    store.insert_sighting(
        post("https://x.test/live", timedelta(days=1)), None, "live-specimen", "resolved"
    )
    db.execute(
        "UPDATE nodes SET created_at = now() - interval '10 days' WHERE id = ANY(%s)",
        (["stale-specimen", "live-specimen"],),
    )

    assert store.expire_specimens() == ["stale-specimen"]
    assert store.get_node("stale-specimen") is None
    assert store.get_node("live-specimen") is not None
    assert store.get_node("new-specimen") is not None
    orphan = db.fetch_one(
        "SELECT node_id, state FROM sightings WHERE post_url = %s", ("https://x.test/stale",)
    )
    assert orphan == {"node_id": None, "state": "unclassified"}
    db.execute("DELETE FROM sightings WHERE post_url LIKE 'https://x.test/%%'")
    db.execute("DELETE FROM nodes WHERE id = ANY(%s)", (["live-specimen", "new-specimen"],))


def _post(url: str) -> Post:
    return Post(
        platform="lemmy",
        source="test",
        post_url=url,
        image_url=url + ".jpg",
        title="t",
        author="a",
        posted_at=datetime.now(UTC),
    )


def test_wall_hides_nsfw_true_and_unlabelled_sightings(client: TestClient) -> None:
    sfw = store.insert_sighting(
        _post("https://x.test/nsfw-wall-sfw"), None, "doomer", "resolved", nsfw=False
    )
    nsfw = store.insert_sighting(
        _post("https://x.test/nsfw-wall-nsfw"), None, "doomer", "resolved", nsfw=True
    )
    unlabelled = store.insert_sighting(
        _post("https://x.test/nsfw-wall-null"), None, "doomer", "resolved"
    )
    try:
        ids = {s.id for s in store.wall(None, limit=500)}
        assert sfw in ids
        assert nsfw not in ids
        assert unlabelled not in ids
    finally:
        db.execute("DELETE FROM sightings WHERE post_url LIKE 'https://x.test/nsfw-wall-%%'")


def test_sightings_for_node_hides_nsfw_true_and_unlabelled(client: TestClient) -> None:
    sfw = store.insert_sighting(
        _post("https://x.test/nsfw-node-sfw"), None, "doomer", "resolved", nsfw=False
    )
    nsfw = store.insert_sighting(
        _post("https://x.test/nsfw-node-nsfw"), None, "doomer", "resolved", nsfw=True
    )
    try:
        ids = {s.id for s in store.sightings_for_node("doomer", limit=500)}
        assert sfw in ids
        assert nsfw not in ids
    finally:
        db.execute("DELETE FROM sightings WHERE post_url LIKE 'https://x.test/nsfw-node-%%'")


def test_set_node_nsfw_and_needing_label(client: TestClient) -> None:
    store.upsert_node(
        MemeNode(
            id="nsfw-test-node",
            name="Nsfw Test Node",
            aliases=[],
            kind="template",
            latin_name=None,
            image_url="https://x.test/nsfw-node.png",
            image_credit_url="https://x.test/credit",
            first_seen=None,
            date_precision=None,
            summary=None,
            status="established",
            sightings_24h=0,
            sightings_7d=0,
            nsfw=None,
        )
    )
    try:
        unlabelled_ids = {n.id for n in store.nodes_needing_nsfw_label()}
        assert "nsfw-test-node" in unlabelled_ids

        store.set_node_nsfw("nsfw-test-node", True)
        node = store.get_node("nsfw-test-node")
        assert node is not None
        assert node.nsfw is True
        assert "nsfw-test-node" not in {n.id for n in store.nodes_needing_nsfw_label()}
        assert "nsfw-test-node" in {n.id for n in store.nodes_needing_nsfw_label(relabel=True)}
    finally:
        db.execute("DELETE FROM nodes WHERE id = 'nsfw-test-node'")


def test_set_sighting_nsfw_and_needing_label(client: TestClient) -> None:
    sid = store.insert_sighting(
        _post("https://x.test/nsfw-sighting-needing"), None, "doomer", "resolved"
    )
    assert sid is not None
    try:
        unlabelled_ids = {r["id"] for r in store.sightings_needing_nsfw_label()}
        assert sid in unlabelled_ids

        store.set_sighting_nsfw(sid, False)
        unlabelled_ids_after = {r["id"] for r in store.sightings_needing_nsfw_label()}
        assert sid not in unlabelled_ids_after
        relabel_ids = {r["id"] for r in store.sightings_needing_nsfw_label(relabel=True)}
        assert sid in relabel_ids
    finally:
        db.execute("DELETE FROM sightings WHERE id = %s", (sid,))
