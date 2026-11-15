import dagre from '@dagrejs/dagre'
import type { Link, MemeNode, Sighting, TreeResponse } from '@contract/types'

export const MAX_CHILDREN = 8
export const NODE_W = 196
export const NODE_H = 88
/** Post groups drawn under the selected meme; the rest fold into one "other posts" group. */
export const MAX_POST_GROUPS = 6

/** The selected meme's own posts, as opposed to ones using another template or family. */
export const OWN_POSTS = '__own'

/** A set of the selected meme's posts, grouped by the template or family they use. */
export interface PostGroup {
  key: string
  label: string
  count: number
  /** The newest post's image. */
  thumb: string
  /** The other meme these posts are stamped with, to open on click; null to filter instead. */
  nodeId: string | null
  /** Which `variantKey`s the group holds (several for the folded "other posts" group). */
  keys: string[]
}

export type FamilyNode =
  | { id: string; kind: 'meme'; x: number; y: number; node: MemeNode; selected: boolean; onPath: boolean }
  | { id: string; kind: 'more'; x: number; y: number; parentId: string; hidden: number }
  | { id: string; kind: 'posts'; x: number; y: number; group: PostGroup }

export interface FamilyEdge {
  id: string
  source: string
  target: string
  inferred: boolean
  onPath: boolean
  /** An edge from the selected meme down to a group of its posts. */
  posts?: boolean
}

export interface FamilyLayout {
  nodes: FamilyNode[]
  edges: FamilyEdge[]
}

export const moreId = (parentId: string) => `more:${parentId}`
export const postsId = (key: string) => `posts:${key}`

/** Which group a post on a meme's page belongs to. */
export const variantKey = (s: Sighting) => s.variant ?? OWN_POSTS

/**
 * The selected meme's posts grouped by `variant`, largest group first. Beyond MAX_POST_GROUPS
 * the smallest fold into one "other posts" group. Flagged posts count only with `showSensitive`.
 */
export function postGroups(tree: TreeResponse, showSensitive: boolean): PostGroup[] {
  const byKey = new Map<string, Sighting[]>()
  for (const s of tree.sightings) {
    if (!showSensitive && s.nsfw !== false) continue
    byKey.set(variantKey(s), [...(byKey.get(variantKey(s)) ?? []), s])
  }
  const groups: PostGroup[] = [...byKey.entries()].map(([key, posts]) => {
    const newest = [...posts].sort((a, b) => b.posted_at.localeCompare(a.posted_at))[0]!
    const other = posts.find((p) => p.node_id !== null && p.node_id !== tree.selected_id)
    return {
      key,
      label: key === OWN_POSTS ? 'in the wild' : key,
      count: posts.length,
      thumb: newest.image_url,
      nodeId: other?.node_id ?? null,
      keys: [key],
    }
  })
  groups.sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
  if (groups.length <= MAX_POST_GROUPS) return groups
  const kept = groups.slice(0, MAX_POST_GROUPS - 1)
  const folded = groups.slice(MAX_POST_GROUPS - 1)
  kept.push({
    key: '__other',
    label: 'other posts',
    count: folded.reduce((sum, g) => sum + g.count, 0),
    thumb: folded[0]!.thumb,
    nodeId: null,
    keys: folded.flatMap((g) => g.keys),
  })
  return kept
}

/** Character-line links whose two ends are both in the family. */
function familyLinks(tree: TreeResponse): Link[] {
  const inFamily = new Set(tree.family_ids)
  return tree.links.filter((l) => l.axis === 'character' && inFamily.has(l.child_id) && inFamily.has(l.parent_id))
}

/** Parent-first pairs along the descent, e.g. "doomer>wojak", used to highlight the path. */
function pathEdgeKeys(path: string[]): Set<string> {
  const keys = new Set<string>()
  path.forEach((id, i) => {
    const parent = path[i + 1]
    if (parent) keys.add(`${id}>${parent}`)
  })
  return keys
}

/**
 * Top-to-bottom layout of the character-line family. A parent shows at most MAX_CHILDREN
 * children plus a "+N" node, unless its id is in `expanded`. The path from the selected
 * meme to the root is flagged for highlighting. The selected meme's posts hang under it as
 * groups (`postGroups`), so a meme with no recorded relatives still shows its family of posts.
 */
export function layoutFamily(
  tree: TreeResponse,
  expanded: ReadonlySet<string>,
  showSensitive = false,
): FamilyLayout {
  const byId = new Map(tree.nodes.map((n) => [n.id, n]))
  const links = familyLinks(tree)
  const path = tree.descent.character
  const pathSet = new Set(path)
  const pathKeys = pathEdgeKeys(path)

  const childrenOf = new Map<string, Link[]>()
  for (const link of links) childrenOf.set(link.parent_id, [...(childrenOf.get(link.parent_id) ?? []), link])

  const rank = (link: Link): [number, number, string] => {
    const child = byId.get(link.child_id)
    return [pathSet.has(link.child_id) ? 0 : 1, -(child?.sightings_7d ?? 0), child?.name ?? link.child_id]
  }
  const compare = (a: Link, b: Link) => {
    const [pa, sa, na] = rank(a)
    const [pb, sb, nb] = rank(b)
    return pa - pb || sa - sb || na.localeCompare(nb)
  }

  const shown: Link[] = []
  const more: { parentId: string; hidden: number }[] = []
  for (const [parentId, kids] of childrenOf) {
    const sorted = [...kids].sort(compare)
    const limit = expanded.has(parentId) ? sorted.length : MAX_CHILDREN
    shown.push(...sorted.slice(0, limit))
    if (sorted.length > limit) more.push({ parentId, hidden: sorted.length - limit })
  }

  const graph = new dagre.graphlib.Graph()
  graph.setGraph({ rankdir: 'TB', nodesep: 14, ranksep: 64, marginx: 20, marginy: 20 })
  graph.setDefaultEdgeLabel(() => ({}))

  const visible = new Set<string>()
  for (const l of shown) {
    visible.add(l.child_id)
    visible.add(l.parent_id)
  }
  const groups = postGroups(tree, showSensitive)
  if (visible.size === 0 || groups.length > 0) visible.add(tree.selected_id)
  for (const id of visible) graph.setNode(id, { width: NODE_W, height: NODE_H })
  for (const l of shown) graph.setEdge(l.parent_id, l.child_id)
  for (const m of more) {
    graph.setNode(moreId(m.parentId), { width: NODE_W, height: NODE_H })
    graph.setEdge(m.parentId, moreId(m.parentId))
  }
  for (const g of groups) {
    graph.setNode(postsId(g.key), { width: NODE_W, height: NODE_H })
    graph.setEdge(tree.selected_id, postsId(g.key))
  }
  dagre.layout(graph)

  const position = (id: string) => {
    const p = graph.node(id)
    return { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 }
  }

  const nodes: FamilyNode[] = []
  for (const id of visible) {
    const node = byId.get(id)
    if (!node) continue
    nodes.push({
      id,
      kind: 'meme',
      ...position(id),
      node,
      selected: id === tree.selected_id,
      onPath: pathSet.has(id),
    })
  }
  for (const m of more) nodes.push({ id: moreId(m.parentId), kind: 'more', ...position(moreId(m.parentId)), ...m })
  for (const g of groups) nodes.push({ id: postsId(g.key), kind: 'posts', ...position(postsId(g.key)), group: g })

  const edges: FamilyEdge[] = shown.map((l) => ({
    id: `${l.child_id}>${l.parent_id}`,
    source: l.parent_id,
    target: l.child_id,
    inferred: l.status === 'inferred',
    onPath: pathKeys.has(`${l.child_id}>${l.parent_id}`),
  }))
  for (const m of more) {
    edges.push({
      id: `${moreId(m.parentId)}>${m.parentId}`,
      source: m.parentId,
      target: moreId(m.parentId),
      inferred: true,
      onPath: false,
    })
  }
  for (const g of groups) {
    edges.push({
      id: `${postsId(g.key)}>${tree.selected_id}`,
      source: tree.selected_id,
      target: postsId(g.key),
      inferred: false,
      onPath: false,
      posts: true,
    })
  }
  return { nodes, edges }
}
