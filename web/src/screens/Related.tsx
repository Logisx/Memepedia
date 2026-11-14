import { useEffect, useMemo, useState } from 'react'
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
  const [load, setLoad] = useState<Load>({ status: 'idle' })

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
    const next = new URLSearchParams(params)
    next.set(side, node.id)
    setParams(next)
  }
  const value = (id: string) => (id === '' ? null : { id, name: names[id] ?? id })
  const nodes = useMemo(
    () => (load.status === 'ready' ? new Map(load.related.nodes.map((n) => [n.id, n])) : new Map<string, MemeNode>()),
    [load],
  )

  return (
    <div className="max-w-6xl px-6 py-6">
      <h1 className="m-0 mb-4 text-3xl font-extrabold">How are two memes related?</h1>
      <div className="flex flex-wrap items-end gap-4">
        <MemePicker label="First meme" value={value(a)} onPick={pick('a')} />
        <span aria-hidden className="pb-1 text-4xl font-extrabold italic">
          &amp;
        </span>
        <MemePicker label="Second meme" value={value(b)} onPick={pick('b')} />
      </div>

      {load.status === 'idle' && (
        <div className="mt-6">
          <p className="font-type text-xl">Pick two memes to see where their families meet.</p>
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
          <p className="m-0 text-3xl font-extrabold leading-snug">{load.related.sentence}</p>
          {load.related.character ? (
            <PathDiagram title="By character" path={load.related.character} nodes={nodes} />
          ) : (
            <p className="font-type m-0 text-lg">No shared character ancestor.</p>
          )}
          {load.related.format ? (
            <PathDiagram title="By format" path={load.related.format} nodes={nodes} />
          ) : (
            <p className="font-type m-0 text-lg">No shared format ancestor.</p>
          )}
        </div>
      )}
    </div>
  )
}
