import dagre from '@dagrejs/dagre'
import type { Link, MemeNode, TreeResponse } from '@contract/types'

export const MAX_CHILDREN = 8
export const NODE_W = 196
export const NODE_H = 88

export type FamilyNode =
  | { id: string; kind: 'meme'; x: number; y: number; node: MemeNode; selected: boolean; onPath: boolean }
  | { id: string; kind: 'more'; x: number; y: number; parentId: string; hidden: number }

export interface FamilyEdge {
  id: string
  source: string
  target: string
  inferred: boolean
  onPath: boolean
}

export interface FamilyLayout {
  nodes: FamilyNode[]
  edges: FamilyEdge[]
}

export const moreId = (parentId: string) => `more:${parentId}`

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
 * meme to the root is flagged for highlighting.
 */
export function layoutFamily(tree: TreeResponse, expanded: ReadonlySet<string>): FamilyLayout {
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
  if (visible.size === 0) visible.add(tree.selected_id)
  for (const id of visible) graph.setNode(id, { width: NODE_W, height: NODE_H })
  for (const l of shown) graph.setEdge(l.parent_id, l.child_id)
  for (const m of more) {
    graph.setNode(moreId(m.parentId), { width: NODE_W, height: NODE_H })
    graph.setEdge(m.parentId, moreId(m.parentId))
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
  return { nodes, edges }
}
