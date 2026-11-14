import type { Sighting } from '@contract/types'

// The wall is meant to feel near-infinite: tiles never disappear as new ones arrive, and
// older posts load in as the viewer scrolls down. This is only a memory guard against an
// unbounded session running for days without a refresh; in practice nobody scrolls (or
// stays on the page) long enough to reach it.
export const MAX_TILES = 2000

export interface MasonryState {
  byId: Map<string, Sighting>
  /** Tile ids per column, top first. Existing tiles never move when new ones arrive. */
  columns: string[][]
}

export const emptyMasonry = (): MasonryState => ({ byId: new Map(), columns: [] })

const byNewest = (a: Sighting, b: Sighting) => b.posted_at.localeCompare(a.posted_at)

/** Deal tiles out row by row, so the newest ones sit along the top. */
function distribute(sorted: Sighting[], count: number): string[][] {
  const columns: string[][] = Array.from({ length: count }, () => [])
  sorted.forEach((s, i) => columns[i % count]?.push(s.id))
  return columns
}

/** The column whose top tile is the oldest (an empty column wins). */
function columnForArrival(columns: string[][], byId: Map<string, Sighting>): number {
  let best = 0
  let bestTime = Infinity
  columns.forEach((col, i) => {
    const top = col[0] ? byId.get(col[0]) : undefined
    const time = top ? Date.parse(top.posted_at) : -Infinity
    if (time < bestTime) {
      best = i
      bestTime = time
    }
  })
  return best
}

function prune(state: MasonryState): MasonryState {
  if (state.byId.size <= MAX_TILES) return state
  const keep = new Set([...state.byId.values()].sort(byNewest).slice(0, MAX_TILES).map((s) => s.id))
  return {
    byId: new Map([...state.byId].filter(([id]) => keep.has(id))),
    columns: state.columns.map((col) => col.filter((id) => keep.has(id))),
  }
}

/** Rebuild from scratch, e.g. when the number of columns changes. */
export function relayout(state: MasonryState, count: number): MasonryState {
  return { byId: state.byId, columns: distribute([...state.byId.values()].sort(byNewest), count) }
}

/** The column with the fewest tiles (an empty column wins), used to balance appended pages. */
function shortestColumn(columns: string[][]): number {
  let best = 0
  let bestLen = Infinity
  columns.forEach((col, i) => {
    if (col.length < bestLen) {
      best = i
      bestLen = col.length
    }
  })
  return best
}

/**
 * Append an older page to the bottom of columns, without reshuffling any tile already
 * placed. Each new tile goes to the shortest column so columns stay roughly balanced.
 */
export function appendOlder(state: MasonryState, incoming: Sighting[]): MasonryState {
  const fresh = incoming.filter((s) => !state.byId.has(s.id))
  if (fresh.length === 0) return state
  const byId = new Map(state.byId)
  fresh.forEach((s) => byId.set(s.id, s))
  const columns = state.columns.map((col) => [...col])
  if (columns.length === 0) columns.push([])
  // incoming is newest-first; keep that order when appended to the bottom of a column.
  for (const s of fresh) {
    columns[shortestColumn(columns)]?.push(s.id)
  }
  return prune({ byId, columns })
}

/** Add sightings. The first batch is dealt out by age; later arrivals drop in at the top of one column. */
export function addSightings(state: MasonryState, incoming: Sighting[], count: number): MasonryState {
  const fresh = incoming.filter((s) => !state.byId.has(s.id))
  // A pending tile can be classified later: swap in the new copy without moving it.
  const changed = incoming.filter((s) => {
    const old = state.byId.get(s.id)
    return old !== undefined && (old.state !== s.state || old.node_id !== s.node_id || old.node_name !== s.node_name)
  })
  if (fresh.length === 0 && changed.length === 0 && state.columns.length === count) return state
  const byId = new Map(state.byId)
  changed.forEach((s) => byId.set(s.id, s))
  fresh.forEach((s) => byId.set(s.id, s))

  if (state.columns.length !== count || state.byId.size === 0) {
    return prune(relayout({ byId, columns: [] }, count))
  }
  const columns = state.columns.map((col) => [...col])
  for (const s of [...fresh].sort((a, b) => a.posted_at.localeCompare(b.posted_at))) {
    columns[columnForArrival(columns, byId)]?.unshift(s.id)
  }
  return prune({ byId, columns })
}
