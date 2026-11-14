CREATE TABLE IF NOT EXISTS nodes (
    id               text PRIMARY KEY,
    name             text NOT NULL,
    aliases          text[] NOT NULL DEFAULT '{}',
    kind             text NOT NULL CHECK (kind IN ('character', 'template', 'phrase', 'format_class')),
    latin_name       text,
    image_url        text,
    image_credit_url text,
    first_seen       date,
    date_precision   text CHECK (date_precision IN ('day', 'month', 'year')),
    summary          text,
    status           text NOT NULL DEFAULT 'established' CHECK (status IN ('established', 'specimen')),
    created_at       timestamptz NOT NULL DEFAULT now()
);

-- One parent per axis: the primary key is the invariant.
CREATE TABLE IF NOT EXISTS links (
    child_id     text NOT NULL REFERENCES nodes (id) ON DELETE CASCADE,
    parent_id    text NOT NULL REFERENCES nodes (id) ON DELETE CASCADE,
    axis         text NOT NULL CHECK (axis IN ('character', 'format')),
    status       text NOT NULL DEFAULT 'inferred' CHECK (status IN ('cited', 'inferred')),
    quote        text,
    source_url   text,
    source_title text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (child_id, axis),
    CHECK (child_id <> parent_id),
    CHECK (
        (status = 'cited' AND quote IS NOT NULL AND source_url IS NOT NULL AND source_title IS NOT NULL)
        OR (status = 'inferred' AND quote IS NULL AND source_url IS NULL AND source_title IS NULL)
    )
);
CREATE INDEX IF NOT EXISTS links_parent_idx ON links (parent_id);

-- seen_at is when the archive ingested the post; the wall's `since` filters on it.
CREATE TABLE IF NOT EXISTS sightings (
    id         text PRIMARY KEY,
    platform   text NOT NULL CHECK (platform IN ('lemmy', 'reddit', 'imgflip', 'mastodon', 'x')),
    source     text,
    post_url   text NOT NULL UNIQUE,
    image_url  text NOT NULL,
    title      text NOT NULL,
    author     text,
    posted_at  timestamptz NOT NULL,
    seen_at    timestamptz NOT NULL DEFAULT now(),
    vision     jsonb,
    node_id    text REFERENCES nodes (id) ON DELETE SET NULL,
    state      text NOT NULL CHECK (state IN ('resolved', 'pending', 'unclassified')),
    cluster_id text,
    CHECK (state <> 'resolved' OR node_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS sightings_seen_idx ON sightings (seen_at DESC);
CREATE INDEX IF NOT EXISTS sightings_posted_idx ON sightings (posted_at DESC);
CREATE INDEX IF NOT EXISTS sightings_node_idx ON sightings (node_id, posted_at DESC);

CREATE TABLE IF NOT EXISTS history (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts         timestamptz NOT NULL DEFAULT now(),
    type       text NOT NULL CHECK (type IN ('traced', 'cited', 'specimen', 'proposal')),
    node_id    text REFERENCES nodes (id) ON DELETE CASCADE,
    message    text NOT NULL,
    source_url text,
    pending    boolean NOT NULL DEFAULT false,
    payload    jsonb
);
CREATE INDEX IF NOT EXISTS history_node_idx ON history (node_id, ts DESC);
