import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link as RouterLink, useSearchParams } from 'react-router'
import type { MemeNode, RelatedResponse } from '@contract/types'
import { MemePicker } from '../components/MemePicker'
import { PathDiagram } from '../components/PathDiagram'
import { getRelated } from '../data'

type Load =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; related: RelatedResponse }

// One-click examples. Both pairs exist in the fixtures and on the live backend.
const EXAMPLES = [
  { a: 'doomer', b: 'yes-chad', label: 'Doomer and Yes Chad' },
  { a: 'swole-doge-vs-cheems', b: 'yes-chad', label: 'Swole Doge vs. Cheems and Yes Chad' },
]

/** Compare two memes: where their lines of descent meet. */
export default function Related() {
  const [params, setParams] = useSearchParams()
  const a = params.get('a') ?? ''
  const b = params.get('b') ?? ''
  const [names, setNames] = useState<Record<string, string>>({})
  // What the two boxes hold. Picking only fills a box; the Compare button (or a link that sets
  // the address) is what starts the comparison.
  const [draft, setDraft] = useState({ a, b })
  const [load, setLoad] = useState<Load>({ status: 'idle' })

  useEffect(() => {
    setDraft({ a, b })
  }, [a, b])

  useEffect(() => {
    if (a === '' || b === '') {
      setLoad({ status: 'idle' })
      return
    }
    if (a === b) {
      setLoad({ status: 'error', message: 'Pick two different memes to compare.' })
      return
    }
    let cancelled = false
    setLoad({ status: 'loading' })
    getRelated(a, b).then(
      (related) => {
        if (cancelled) return
        setNames((prev) => ({ ...prev, ...Object.fromEntries(related.nodes.map((n) => [n.id, n.name])) }))
        setLoad({ status: 'ready', related })
      },
      (e: unknown) => !cancelled && setLoad({ status: 'error', message: e instanceof Error ? e.message : String(e) }),
    )
    return () => {
      cancelled = true
    }
  }, [a, b])

  const pick = (side: 'a' | 'b') => (node: MemeNode) => {
    setNames((prev) => ({ ...prev, [node.id]: node.name }))
    setDraft((prev) => ({ ...prev, [side]: node.id }))
  }
  // Typed away from the picked meme without choosing a new one: Compare must not use the stale pick.
  const clear = (side: 'a' | 'b') => () => setDraft((prev) => ({ ...prev, [side]: '' }))
  const bothPicked = draft.a !== '' && draft.b !== ''
  const same = bothPicked && draft.a === draft.b
  const compare = (e: FormEvent) => {
    e.preventDefault()
    if (bothPicked && !same) setParams(new URLSearchParams({ a: draft.a, b: draft.b }))
  }
  const value = (id: string) => (id === '' ? null : { id, name: names[id] ?? id })
  const nodes = useMemo(
    () => (load.status === 'ready' ? new Map(load.related.nodes.map((n) => [n.id, n])) : new Map<string, MemeNode>()),
    [load],
  )

  return (
    <div className="max-w-6xl px-4 py-6 md:px-6">
      <h1 className="m-0 mb-4 text-2xl font-extrabold md:text-3xl">How are two memes related?</h1>
      <form onSubmit={compare} className="flex flex-wrap items-end gap-4">
        <MemePicker label="First meme" value={value(draft.a)} onPick={pick('a')} onClear={clear('a')} />
        <span aria-hidden className="flex flex-col items-center pb-1">
          <span className="text-4xl font-extrabold">&amp;</span>
          {bothPicked && (
            <button
              type="button"
              onClick={() => setParams(new URLSearchParams({ a: draft.b, b: draft.a }))}
              className="font-type cursor-pointer border-0 bg-transparent p-0 text-sm underline"
              aria-label="Swap the two memes"
            >
              swap
            </button>
          )}
        </span>
        <MemePicker label="Second meme" value={value(draft.b)} onPick={pick('b')} onClear={clear('b')} />
        <button
          type="submit"
          disabled={!bothPicked || same}
          className="font-type w-full cursor-pointer border-2 border-ink bg-ink px-6 py-2 text-xl text-paper disabled:cursor-not-allowed disabled:opacity-40 md:w-auto"
        >
          Compare
        </button>
      </form>
      {same && <p className="font-type mt-2 text-lg text-stamp">Pick two different memes to compare.</p>}

      {load.status === 'idle' && (
        <div className="mt-6">
          <p className="font-type text-xl">Pick two memes, then press Compare to see where their families meet.</p>
          <p className="font-type text-lg">
              Try:{' '}
              {EXAMPLES.map((ex, i) => (
                <span key={ex.a + ex.b}>
                  {i > 0 && ' · '}
                  <RouterLink to={`/related?a=${ex.a}&b=${ex.b}`}>{ex.label}</RouterLink>
                </span>
              ))}
            </p>
        </div>
      )}
      {load.status === 'loading' && <p className="font-type mt-6 text-xl">Comparing the two family trees…</p>}
      {load.status === 'error' && <p className="mt-6 text-2xl text-stamp">{load.message}</p>}
      {load.status === 'ready' && (
        <div className="mt-6 space-y-5">
          <p className="m-0 text-2xl font-extrabold leading-snug md:text-3xl">{load.related.sentence}</p>
          {load.related.character && <PathDiagram title="By character" path={load.related.character} nodes={nodes} />}
          {load.related.format && <PathDiagram title="By format" path={load.related.format} nodes={nodes} />}
          {!load.related.character && <p className="font-type m-0 text-lg text-ink-soft">No shared character ancestor.</p>}
          {!load.related.format && <p className="font-type m-0 text-lg text-ink-soft">No shared format ancestor.</p>}
        </div>
      )}
    </div>
  )
}
