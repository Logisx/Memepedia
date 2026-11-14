import { useEffect, useRef, useState } from 'react'
import type { MemeNode } from '@contract/types'
import { searchNodes } from '../data'
import { NodeThumb } from './SpecimenCard'

interface Props {
  label: string
  /** The chosen meme, or null. `name` is what the box shows. */
  value: { id: string; name: string } | null
  onPick: (node: MemeNode) => void
  /** Called when the typed text no longer matches the picked meme's name, so the stale pick isn't reused. */
  onClear?: () => void
}

/** A search box that only accepts a pick from the suggestions. */
export function MemePicker({ label, value, onPick, onClear }: Props) {
  const [text, setText] = useState(value?.name ?? '')
  const [suggestions, setSuggestions] = useState<MemeNode[]>([])
  const [open, setOpen] = useState(false)
  // So an in-flight Enter lookup can tell whether the text has since moved on.
  const textRef = useRef(text)
  useEffect(() => {
    textRef.current = text
  }, [text])

  useEffect(() => {
    // Only resync from an external pick (swap, a fixture link, …). A clear-to-null caused by the
    // user typing away from the old pick must not stomp on what they're mid-typing.
    if (value) setText(value.name)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally ignores a clear-to-null
  }, [value?.id, value?.name])

  useEffect(() => {
    if (!open) return
    let cancelled = false
    const timer = setTimeout(() => {
      searchNodes(text, 6).then(
        (res) => !cancelled && setSuggestions(res.nodes),
        () => !cancelled && setSuggestions([]),
      )
    }, 150)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [text, open])

  return (
    <div className="relative min-w-64 flex-1">
      <label className="font-type block text-sm uppercase tracking-widest">
        {label}
        <input
          type="search"
          value={text}
          onChange={(e) => {
            const next = e.target.value
            setText(next)
            setOpen(true)
            // The box no longer shows the picked meme's name: the old pick must not be reused.
            if (value && next !== value.name) onClear?.()
          }}
          onFocus={(e) => {
            e.target.select()
            setOpen(true)
          }}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            // Enter takes the top match for what's typed right now, not a stale debounced suggestion.
            if (e.key !== 'Enter' || !open) return
            e.preventDefault()
            const current = text
            searchNodes(current, 1).then((res) => {
              const top = res.nodes[0]
              if (!top || textRef.current !== current) return
              onPick(top)
              setText(top.name)
              setOpen(false)
            })
          }}
          placeholder="Pick a meme…"
          className="mt-1 block w-full border-2 border-ink bg-paper px-3 py-2 text-xl normal-case tracking-normal"
        />
      </label>
      {open && suggestions.length > 0 && (
        <ul className="absolute z-20 m-0 mt-1 w-full list-none border-2 border-ink bg-paper p-0 shadow-[4px_4px_0_var(--color-ink)]">
          {suggestions.map((node) => (
            <li key={node.id}>
              <button
                type="button"
                onMouseDown={() => {
                  onPick(node)
                  setText(node.name)
                  setOpen(false)
                }}
                className="flex w-full cursor-pointer items-center gap-3 border-0 bg-transparent p-2 text-left hover:bg-paper-deep"
              >
                <NodeThumb node={node} className="h-10 w-10" />
                <span className="text-xl font-bold">{node.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
