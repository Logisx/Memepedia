import { useEffect, useState } from 'react'

/** F0 scaffolding: print whatever a data call returns, as text. Replaced screen by screen. */
export function Raw<T>({ label, load }: { label: string; load: () => Promise<T> }) {
  const [state, setState] = useState<{ data?: T; error?: string }>({})

  useEffect(() => {
    let cancelled = false
    load().then(
      (data) => !cancelled && setState({ data }),
      (e: unknown) => !cancelled && setState({ error: e instanceof Error ? e.message : String(e) }),
    )
    return () => {
      cancelled = true
    }
  }, [load])

  return (
    <section className="p-6">
      <h2 className="font-type text-xl">{label}</h2>
      {state.error && <p className="text-stamp">Error: {state.error}</p>}
      {!state.error && state.data === undefined && <p>Loading…</p>}
      {state.data !== undefined && (
        <pre className="mt-2 overflow-auto text-sm">{JSON.stringify(state.data, null, 2)}</pre>
      )}
    </section>
  )
}
