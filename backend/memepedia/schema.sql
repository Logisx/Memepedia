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
-- Nullable: null = not yet labelled. Idempotent so this file doubles as the migration for an
-- existing database (it runs on every init_schema() call, e.g. at app startup).
ALTER TABLE nodes ADD COLUMN IF NOT EXISTS nsfw boolean;

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
-- Nullable: null = not yet labelled; the wall and live feed only ever show nsfw = false.
ALTER TABLE sightings ADD COLUMN IF NOT EXISTS nsfw boolean;
CREATE INDEX IF NOT EXISTS sightings_seen_idx ON sightings (seen_at DESC);
CREATE INDEX IF NOT EXISTS sightings_posted_idx ON sightings (posted_at DESC);
CREATE INDEX IF NOT EXISTS sightings_node_idx ON sightings (node_id, posted_at DESC);
-- Why the image was never looked at (download or decode failure); null once it has been read.
ALTER TABLE sightings ADD COLUMN IF NOT EXISTS look_error text;
-- The same picture posted again under another URL: it points at the sighting kept on the wall,
-- shares its stamp and is left out of every list and count (memepedia/dedupe.py).
ALTER TABLE sightings ADD COLUMN IF NOT EXISTS duplicate_of text REFERENCES sightings (id) ON DELETE SET NULL;
-- 256-bit difference hash of the image, 64 hex characters (memepedia/imageprep.py).
ALTER TABLE sightings ADD COLUMN IF NOT EXISTS fingerprint text;
CREATE INDEX IF NOT EXISTS sightings_image_url_idx ON sightings (image_url);
CREATE INDEX IF NOT EXISTS sightings_duplicate_idx ON sightings (duplicate_of);

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

-- Cost guards (budget.py): paid units spent per hour and kind (Context.dev credits, Gemini calls,
-- background traces), shared by every container and summed over a rolling window.
CREATE TABLE IF NOT EXISTS spend (
    hour   timestamptz NOT NULL,
    kind   text NOT NULL,
    amount double precision NOT NULL DEFAULT 0,
    PRIMARY KEY (hour, kind)
);

-- Small shared flags: the kill switch, cap overrides, throttles and the webhook heartbeat.
CREATE TABLE IF NOT EXISTS app_state (
    key        text PRIMARY KEY,
    value      text NOT NULL DEFAULT '',
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Context.dev monitors this archive created, each with its own webhook signing secret.
CREATE TABLE IF NOT EXISTS webhook_monitors (
    id         text PRIMARY KEY,
    feed_key   text NOT NULL,
    secret     text,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Webhook event ids already accepted, so a retried or replayed delivery runs nothing twice.
CREATE TABLE IF NOT EXISTS webhook_events (
    id          text PRIMARY KEY,
    received_at timestamptz NOT NULL DEFAULT now()
);
