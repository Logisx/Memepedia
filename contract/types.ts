/**
 * Memepedia data contract. The backend returns exactly these shapes as JSON;
 * the frontend consumes exactly these shapes. Fixtures in ./fixtures follow them.
 * Change this file only by agreement between both halves.
 */

/** What a node is. A node is a meme format, never a single post. */
export type Kind = "character" | "template" | "phrase" | "format_class";

/** The two lines of descent: who a meme is about, and how it is built. */
export type Axis = "character" | "format";

/** "cited" has a verbatim quote from a web page; "inferred" is shown dashed as "citation needed". */
export type LinkStatus = "cited" | "inferred";

export type Platform = "lemmy" | "reddit" | "imgflip" | "mastodon" | "x";

export interface MemeNode {
  /** URL-safe slug, e.g. "doomer". */
  id: string;
  name: string;
  aliases: string[];
  kind: Kind;
  /** Mock-Latin museum name, e.g. "Wojakus melancholicus". */
  latin_name: string | null;
  image_url: string | null;
  /** Page the image came from; link it as the credit. */
  image_credit_url: string | null;
  /** ISO date "2018-09-01". Show only as much as date_precision allows. */
  first_seen: string | null;
  date_precision: "day" | "month" | "year" | null;
  summary: string | null;
  /** "specimen" = detected from live sightings, not yet established. */
  status: "established" | "specimen";
  sightings_24h: number;
  sightings_7d: number;
  /**
   * null = not yet labelled. The frontend blurs the image (click-to-reveal) when this is
   * true OR null; nodes are never removed, only sightings are. See README "NSFW policy".
   */
  nsfw: boolean | null;
}

export interface Link {
  child_id: string;
  parent_id: string;
  axis: Axis;
  status: LinkStatus;
  /** One sentence copied verbatim from source_url. Null when inferred. */
  quote: string | null;
  source_url: string | null;
  source_title: string | null;
}

/** One post seen in the wild. */
export interface Sighting {
  id: string;
  platform: Platform;
  post_url: string;
  image_url: string;
  title: string;
  author: string | null;
  /** ISO datetime of the post itself; "spotted N min ago" is computed from this. */
  posted_at: string;
  /** Null while the sighting is pending or unclassified. */
  node_id: string | null;
  node_name: string | null;
  state: "resolved" | "pending" | "unclassified";
  /**
   * null = not yet labelled. The backend never returns a sighting where this is not
   * exactly `false` (wall, week, tree, SSE); the frontend defensively hides any that slip
   * through. See README "NSFW policy".
   */
  nsfw: boolean | null;
}

export interface HistoryItem {
  id: string;
  ts: string;
  type: "traced" | "cited" | "specimen" | "proposal";
  message: string;
  source_url: string | null;
  /** True for visitor proposals not yet accepted. */
  pending: boolean;
}

/** GET /api/wall?since=<iso>&limit=60, or GET /api/wall?before=<cursor>&limit=N for older pages */
export interface WallResponse {
  sightings: Sighting[];
  /** Pass back as `since` on the next poll. */
  server_time: string;
  sources_watched: number;
  /**
   * Opaque cursor for the page just older than this one; pass it back as `before`.
   * Null once there are no more older sightings. `limit` is capped at 100 when `before` is used.
   */
  next_before: string | null;
}

/** GET /api/nodes?q=<text>&limit=20 (empty q returns a popular mix) */
export interface NodesResponse {
  nodes: MemeNode[];
}

/** GET /api/nodes/random */
export interface RandomResponse {
  id: string;
}

/** GET /api/tree/{id} */
export interface TreeResponse {
  selected_id: string;
  /** Every node referenced anywhere in this response. */
  nodes: MemeNode[];
  /** Ids of the character-line family; the family map lays out only these. */
  family_ids: string[];
  /** All links among `nodes`, both axes. The map draws axis "character" only. */
  links: Link[];
  /** Ids from the selected meme back to its root, oldest last. */
  descent: { character: string[]; format: string[] };
  /** Recent sightings of the selected meme, newest first. */
  sightings: Sighting[];
  history: HistoryItem[];
}

export interface AncestorPath {
  ancestor_id: string;
  /** Ids from meme A up to the ancestor, inclusive. */
  path_a: string[];
  /** Ids from meme B up to the ancestor, inclusive. */
  path_b: string[];
}

/** GET /api/related?a=<id>&b=<id> */
export interface RelatedResponse {
  a_id: string;
  b_id: string;
  nodes: MemeNode[];
  character: AncestorPath | null;
  format: AncestorPath | null;
  /** Ready-to-show sentence, e.g. "By character: both descend from Wojak (2010)." */
  sentence: string;
}

export interface RisingFamily {
  node: MemeNode;
  count_24h: number;
  daily_mean_prior: number;
}

/** GET /api/week */
export interface WeekResponse {
  rising: RisingFamily[];
  new_specimens: MemeNode[];
}

/**
 * POST /api/trace  body: { query: string }
 * Response is a server-sent event stream. Each event's `data` is one TraceEvent as JSON.
 * Order: status* -> chain (all links inferred) -> link* (as each is checked) -> done | error.
 */
export type TraceEvent =
  | { type: "status"; message: string }
  | { type: "chain"; nodes: MemeNode[]; links: Link[] }
  | { type: "link"; link: Link }
  | { type: "done"; node_id: string }
  | { type: "error"; message: string };

/** POST /api/identify  multipart form with field "image" */
export interface IdentifyResponse {
  /** Set when the image matches a meme already in the archive. */
  node_id: string | null;
  /** When node_id is null, send this as the query to POST /api/trace. */
  trace_query: string | null;
  guess: string | null;
  overlaid_text: string | null;
}

/** POST /api/proposals  body: { node_id: string; url: string; note: string } */
export interface ProposalResponse {
  /** True when the URL contained a qualifying sentence and a link became cited. */
  accepted: boolean;
  message: string;
  link: Link | null;
}
