/**
 * The only module that fetches data. Everything else imports from here.
 *
 * VITE_API_BASE unset: serve the JSON fixtures in contract/fixtures/ and simulate
 * the live behaviours (wall drip-in, trace replay).
 * VITE_API_BASE set: call the real endpoints listed in contract/README.md.
 */
import type {
  IdentifyResponse,
  MemeNode,
  NodesResponse,
  ProposalResponse,
  RandomResponse,
  RelatedResponse,
  Sighting,
  TraceEvent,
  TreeResponse,
  WallResponse,
  WeekResponse,
} from '@contract/types'

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') || ''
export const usingFixtures = API_BASE === ''

/* ---------- fixtures ---------- */

const fixtureFiles = import.meta.glob('../../contract/fixtures/*.json', {
  eager: true,
  import: 'default',
}) as Record<string, unknown>

function fixture<T>(name: string): T | undefined {
  return fixtureFiles[`../../contract/fixtures/${name}.json`] as T | undefined
}

function requireFixture<T>(name: string): T {
  const found = fixture<T>(name)
  if (found === undefined) throw new Error(`No fixture named ${name}.json`)
  return found
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

/* ---------- real API helpers ---------- */

async function failureMessage(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { error?: string }
    if (body.error) return body.error
  } catch {
    /* not JSON; fall through */
  }
  return `Request failed (${res.status})`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init)
  if (!res.ok) throw new Error(await failureMessage(res))
  return (await res.json()) as T
}

/* ---------- wall (fixture drip-in) ---------- */

const HELD_BACK = 10
const NEWEST_AGE_MS = 2 * 60_000

interface Dripped {
  sighting: Sighting
  releasedAt: number
}

interface WallMock {
  visible: Dripped[]
  held: Sighting[]
  nextReleaseAt: number
}

let wallMock: WallMock | undefined

const nextDelay = () => 6_000 + Math.random() * 4_000

function startWallMock(): WallMock {
  const all = requireFixture<WallResponse>('wall').sightings
  const newestFirst = [...all].sort((a, b) => b.posted_at.localeCompare(a.posted_at))
  const held = newestFirst.slice(0, HELD_BACK).reverse() // oldest of the held-back released first
  const visible = newestFirst.slice(HELD_BACK)
  const now = Date.now()
  const newest = visible[0]
  const shift = newest ? now - NEWEST_AGE_MS - Date.parse(newest.posted_at) : 0
  return {
    visible: visible.map((s) => ({
      sighting: { ...s, posted_at: new Date(Date.parse(s.posted_at) + shift).toISOString() },
      releasedAt: 0,
    })),
    held,
    nextReleaseAt: now + nextDelay(),
  }
}

function releaseDue(mock: WallMock, now: number): void {
  while (mock.held.length > 0 && now >= mock.nextReleaseAt) {
    const next = mock.held.shift()
    if (!next) break
    const postedAt = new Date(now - Math.random() * 45_000).toISOString()
    mock.visible.unshift({ sighting: { ...next, posted_at: postedAt }, releasedAt: now })
    mock.nextReleaseAt += nextDelay()
  }
}

function mockWall(since: string | undefined, limit: number): WallResponse {
  wallMock ??= startWallMock()
  const now = Date.now()
  releaseDue(wallMock, now)
  const sinceMs = since ? Date.parse(since) : undefined
  const fresh = wallMock.visible.filter((d) => sinceMs === undefined || d.releasedAt > sinceMs)
  return {
    sightings: fresh.slice(0, limit).map((d) => d.sighting),
    server_time: new Date(now).toISOString(),
    sources_watched: requireFixture<WallResponse>('wall').sources_watched,
  }
}

/** Recent sightings, newest first. Pass the previous response's `server_time` as `since`. */
export async function getWall(since?: string, limit = 60): Promise<WallResponse> {
  if (usingFixtures) return mockWall(since, limit)
  const params = new URLSearchParams({ limit: String(limit) })
  if (since) params.set('since', since)
  return request<WallResponse>(`/api/wall?${params}`)
}

/* ---------- nodes ---------- */

function matches(node: MemeNode, q: string): boolean {
  const needle = q.trim().toLowerCase()
  if (needle === '') return true
  return [node.name, ...node.aliases].some((n) => n.toLowerCase().includes(needle))
}

export async function searchNodes(q: string, limit = 20): Promise<NodesResponse> {
  if (!usingFixtures) {
    return request<NodesResponse>(`/api/nodes?${new URLSearchParams({ q, limit: String(limit) })}`)
  }
  const nodes = requireFixture<NodesResponse>('nodes').nodes
  const found = nodes.filter((n) => matches(n, q)).sort((a, b) => b.sightings_7d - a.sightings_7d)
  return { nodes: found.slice(0, limit) }
}

export async function randomNode(): Promise<RandomResponse> {
  if (!usingFixtures) return request<RandomResponse>('/api/nodes/random')
  const pool = requireFixture<NodesResponse>('nodes').nodes.filter((n) => n.kind !== 'format_class')
  const pick = pool[Math.floor(Math.random() * pool.length)]
  if (!pick) throw new Error('No nodes in fixtures')
  return { id: pick.id }
}

/* ---------- tree, related, week ---------- */

export async function getTree(id: string): Promise<TreeResponse> {
  if (!usingFixtures) return request<TreeResponse>(`/api/tree/${encodeURIComponent(id)}`)
  return fixture<TreeResponse>(`tree-${id}`) ?? requireFixture<TreeResponse>('tree-wojak')
}

export async function getRelated(a: string, b: string): Promise<RelatedResponse> {
  if (!usingFixtures) {
    return request<RelatedResponse>(`/api/related?${new URLSearchParams({ a, b })}`)
  }
  const found = fixture<RelatedResponse>(`related-${a}-${b}`) ?? fixture<RelatedResponse>(`related-${b}-${a}`)
  if (!found) throw new Error(`No mock comparison for ${a} and ${b}`)
  return found
}

export async function getWeek(): Promise<WeekResponse> {
  if (!usingFixtures) return request<WeekResponse>('/api/week')
  return requireFixture<WeekResponse>('week')
}

/* ---------- trace (event stream) ---------- */

interface TraceStep {
  delay_ms: number
  event: TraceEvent
}

/** Parse server-sent events out of a text stream; each `data:` payload is one TraceEvent. */
async function readEventStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: TraceEvent) => void,
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = blocks.pop() ?? ''
    for (const block of blocks) emitBlock(block, onEvent)
  }
  if (buffer.trim() !== '') emitBlock(buffer, onEvent)
}

function emitBlock(block: string, onEvent: (event: TraceEvent) => void): void {
  const data = block
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('\n')
  if (data !== '') onEvent(JSON.parse(data) as TraceEvent)
}

/** Stream a trace. Resolves when the stream ends; abort with `signal`. */
export async function trace(
  query: string,
  onEvent: (event: TraceEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  if (usingFixtures) {
    for (const step of requireFixture<TraceStep[]>('trace-sample')) {
      await sleep(step.delay_ms)
      if (signal?.aborted) return
      onEvent(step.event)
    }
    return
  }
  const res = await fetch(`${API_BASE}/api/trace`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ query }),
    signal,
  })
  if (!res.ok) throw new Error(await failureMessage(res))
  if (!res.body) throw new Error('The server sent no stream')
  await readEventStream(res.body, onEvent)
}

/* ---------- identify and proposals ---------- */

// The fixtures hold two answers each. Alternate so both branches of the UI get exercised:
// identify: known meme, then unknown (starts a trace); proposals: accepted, then rejected.
let identifyCalls = 0
let proposalCalls = 0

export async function identify(image: File): Promise<IdentifyResponse> {
  if (usingFixtures) {
    const answers = requireFixture<IdentifyResponse[]>('identify')
    const answer = answers[identifyCalls++ % answers.length]
    if (!answer) throw new Error('identify.json is empty')
    await sleep(800)
    return answer
  }
  const form = new FormData()
  form.append('image', image)
  return request<IdentifyResponse>('/api/identify', { method: 'POST', body: form })
}

export async function propose(nodeId: string, url: string, note: string): Promise<ProposalResponse> {
  if (usingFixtures) {
    const answers = requireFixture<ProposalResponse[]>('proposal')
    const answer = answers[proposalCalls++ % answers.length]
    if (!answer) throw new Error('proposal.json is empty')
    await sleep(900)
    return answer
  }
  return request<ProposalResponse>('/api/proposals', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ node_id: nodeId, url, note }),
  })
}
