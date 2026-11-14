import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import type { MemeNode } from '@contract/types'
import { randomNode, searchNodes } from '../data'
import { NodeThumb } from './SpecimenCard'

/** Search with suggestions from the nodes endpoint, plus the random button. */
export function SearchBox() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState<MemeNode[]>([])
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string>()

  useEffect(() => {
    let cancelled = false
    const timer = setTimeout(() => {
      searchNodes(query, 6).then(
        (res) => !cancelled && setSuggestions(res.nodes),
        () => !cancelled && setSuggestions([]),
      )
    }, 150)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [query])

  async function submit(e: FormEvent) {
    e.preventDefault()
    const q = query.trim()
    if (q === '') return
    setBusy(true)
    setError(undefined)
    try {
      const { nodes } = await searchNodes(q, 1)
      const match = nodes[0]
      navigate(match ? `/meme/${match.id}` : `/trace?q=${encodeURIComponent(q)}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function surprise() {
    setBusy(true)
    setError(undefined)
    try {
      navigate(`/meme/${(await randomNode()).id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative min-w-72 flex-1">
      <form onSubmit={submit} className="flex gap-2">
        <input
          type="search"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder="Search a meme, or name one we don't know…"
          aria-label="Search memes"
          className="font-type min-w-0 flex-1 border-2 border-ink bg-paper px-3 py-2 text-xl"
        />
        <button
          type="submit"
          disabled={busy || query.trim() === ''}
          className="font-type cursor-pointer border-2 border-ink bg-ink px-4 text-xl text-paper disabled:opacity-50"
        >
          Look up
        </button>
        <button
          type="button"
          onClick={surprise}
          disabled={busy}
          className="font-type cursor-pointer border-2 border-ink bg-paper px-4 text-xl disabled:opacity-50"
        >
          Random
        </button>
      </form>
      {error && <p className="font-type m-0 mt-1 text-stamp">Search failed: {error}</p>}
      {open && suggestions.length > 0 && (
        <ul className="absolute z-20 m-0 mt-1 w-full list-none border-2 border-ink bg-paper p-0 shadow-[4px_4px_0_var(--color-ink)]">
          {suggestions.map((node) => (
            <li key={node.id}>
              <button
                type="button"
                onMouseDown={() => navigate(`/meme/${node.id}`)}
                className="flex w-full cursor-pointer items-center gap-3 border-0 bg-transparent p-2 text-left hover:bg-paper-deep"
              >
                <NodeThumb node={node} className="h-10 w-10" />
                <span className="text-xl font-bold">{node.name}</span>
                {node.latin_name && <span className="text-base italic">{node.latin_name}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
