import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import type { TraceEvent } from '@contract/types'
import { trace } from '../data'

export default function Trace() {
  const [params] = useSearchParams()
  const query = params.get('q') ?? ''
  const [events, setEvents] = useState<TraceEvent[]>([])
  const [error, setError] = useState<string>()

  useEffect(() => {
    const controller = new AbortController()
    setEvents([])
    setError(undefined)
    trace(query, (event) => setEvents((prev) => [...prev, event]), controller.signal).catch((e: unknown) => {
      if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e))
    })
    return () => controller.abort()
  }, [query])

  return (
    <section className="p-6">
      <h2 className="font-type text-xl">POST /api/trace — “{query}”</h2>
      {error && <p className="text-stamp">Error: {error}</p>}
      <pre className="mt-2 overflow-auto text-sm">{JSON.stringify(events, null, 2)}</pre>
    </section>
  )
}
