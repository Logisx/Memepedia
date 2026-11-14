import { useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { Link as RouterLink, useNavigate, useSearchParams } from 'react-router'
import type { Link, MemeNode, TraceEvent } from '@contract/types'
import { DescentStrip } from '../components/DescentStrip'
import { trace } from '../data'

const OPEN_LINEAGE_DELAY_MS = 2_500

interface LogLine {
  at: number
  text: string
  tone: 'plain' | 'good' | 'warn'
}

interface TraceState {
  log: LogLine[]
  nodes: MemeNode[]
  links: Link[]
  doneId?: string
  error?: string
}

type Action = { type: 'reset' } | { type: 'event'; event: TraceEvent; at: number } | { type: 'fail'; message: string; at: number }

const sameLink = (a: Link, b: Link) => a.child_id === b.child_id && a.parent_id === b.parent_id && a.axis === b.axis

function reduce(state: TraceState, action: Action): TraceState {
  if (action.type === 'reset') return { log: [], nodes: [], links: [] }
  const line = (text: string, tone: LogLine['tone'] = 'plain'): LogLine[] => [...state.log, { at: action.at, text, tone }]
  if (action.type === 'fail') return { ...state, error: action.message, log: line(`Trace failed: ${action.message}`, 'warn') }

  const event = action.event
  switch (event.type) {
    case 'status':
      return { ...state, log: line(event.message) }
    case 'chain':
      return {
        ...state,
        nodes: event.nodes,
        links: event.links,
        log: line(`Drafted a chain: ${event.nodes.map((n) => n.name).join(' → ')}. Checking each link…`),
      }
    case 'link': {
      const cited = event.link.status === 'cited'
      const names = (id: string) => state.nodes.find((n) => n.id === id)?.name ?? id
      return {
        ...state,
        links: state.links.map((l) => (sameLink(l, event.link) ? event.link : l)),
        log: line(
          cited
            ? `Found a source: ${names(event.link.child_id)} → ${names(event.link.parent_id)}`
            : `No quote found for ${names(event.link.child_id)} → ${names(event.link.parent_id)}`,
          cited ? 'good' : 'warn',
        ),
      }
    }
    case 'done':
      return { ...state, doneId: event.node_id, log: line('Trace complete. Opening the lineage…', 'good') }
    case 'error':
      return { ...state, error: event.message, log: line(`Trace failed: ${event.message}`, 'warn') }
  }
}

const formatElapsed = (ms: number) => `${String(Math.floor(ms / 60000)).padStart(2, '0')}:${(ms / 1000 % 60).toFixed(1).padStart(4, '0')}`

/** Live trace of a meme the archive does not know yet: field log on the left, the chain on the right. */
export default function Trace() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const query = params.get('q')?.trim() ?? ''
  const [state, dispatch] = useReducer(reduce, { log: [], nodes: [], links: [] })
  const [attempt, setAttempt] = useState(0)
  const started = useRef(0)

  useEffect(() => {
    if (query === '') return
    const controller = new AbortController()
    started.current = Date.now()
    dispatch({ type: 'reset' })
    const elapsed = () => Date.now() - started.current
    trace(query, (event) => dispatch({ type: 'event', event, at: elapsed() }), controller.signal).catch((e: unknown) => {
      if (!controller.signal.aborted) {
        dispatch({ type: 'fail', message: e instanceof Error ? e.message : String(e), at: elapsed() })
      }
    })
    return () => controller.abort()
  }, [query, attempt])

  useEffect(() => {
    if (!state.doneId) return
    const timer = setTimeout(() => navigate(`/meme/${state.doneId}`, { replace: true }), OPEN_LINEAGE_DELAY_MS)
    return () => clearTimeout(timer)
  }, [state.doneId, navigate])

  const nodesById = useMemo(() => new Map(state.nodes.map((n) => [n.id, n])), [state.nodes])
  const descent = useMemo(() => state.nodes.map((n) => n.id), [state.nodes])
  const running = !state.doneId && !state.error

  if (query === '') {
    return (
      <div className="p-8">
        <p className="font-type text-2xl">Nothing to trace. Search for a meme on the wall first.</p>
        <RouterLink to="/" className="font-type text-xl">
          ← Back to the wall
        </RouterLink>
      </div>
    )
  }

  return (
    <div className="flex min-h-[calc(100vh-4.25rem)] flex-col px-6 py-4">
      <div className="mb-4 flex flex-wrap items-baseline gap-4">
        <h1 className="m-0 text-3xl font-extrabold">Tracing “{query}”</h1>
        <RouterLink to="/" className="font-type text-lg">
          ← Back to the wall
        </RouterLink>
      </div>

      <div className="flex min-h-0 flex-1 flex-wrap gap-6">
        <section aria-label="Field log" className="w-full shrink-0 border-2 border-ink p-3 lg:w-[28rem]">
          <h2 className="font-type m-0 mb-2 border-b border-ink pb-1 text-lg uppercase tracking-widest">Field log</h2>
          <ol className="font-type m-0 list-none space-y-1 p-0 text-lg" aria-live="polite">
            {state.log.map((l, i) => (
              <li key={i} className={l.tone === 'good' ? 'text-cited' : l.tone === 'warn' ? 'text-stamp' : undefined}>
                <span className="mr-2 text-ink-soft">[{formatElapsed(l.at)}]</span>
                {l.text}
              </li>
            ))}
            {running && <li className="animate-pulse">▍</li>}
          </ol>
          {state.error && (
            <button
              onClick={() => setAttempt((n) => n + 1)}
              className="font-type mt-3 cursor-pointer border-2 border-ink px-4 py-1 text-xl"
            >
              Try again
            </button>
          )}
          {state.doneId && (
            <button
              onClick={() => navigate(`/meme/${state.doneId}`, { replace: true })}
              className="font-type mt-3 cursor-pointer border-2 border-ink bg-ink px-4 py-1 text-xl text-paper"
            >
              Open the lineage now
            </button>
          )}
        </section>

        <section aria-label="Descent chain" className="h-[26rem] min-w-0 flex-1">
          {state.nodes.length === 0 ? (
            <p className="font-type text-xl text-ink-soft">
              {state.error ? 'No chain could be drawn.' : 'Waiting for the first draft of the chain…'}
            </p>
          ) : (
            <DescentStrip axis="character" descent={descent} nodesById={nodesById} links={state.links} checking={running} />
          )}
        </section>
      </div>
    </div>
  )
}
