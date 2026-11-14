import { useState, type FormEvent } from 'react'
import type { HistoryItem, Link, ProposalResponse, Sighting } from '@contract/types'
import { propose } from '../data'
import { timeAgo } from '../lib/time'

type Tab = 'sightings' | 'history' | 'suggest'

const TABS: { id: Tab; label: string }[] = [
  { id: 'sightings', label: 'Sightings' },
  { id: 'history', label: 'History' },
  { id: 'suggest', label: 'Suggest a source' },
]

const HISTORY_LABEL: Record<HistoryItem['type'], string> = {
  traced: 'traced',
  cited: 'cited',
  specimen: 'specimen',
  proposal: 'proposal',
}

interface Props {
  nodeId: string
  sightings: Sighting[]
  history: HistoryItem[]
  /** Called when a proposal turned a link into a cited one. */
  onCited: (link: Link) => void
}

export function SidePanel({ nodeId, sightings, history, onCited }: Props) {
  const [tab, setTab] = useState<Tab>('sightings')
  return (
    <aside className="flex h-full min-h-0 w-[26rem] shrink-0 flex-col border-l border-ink">
      <div role="tablist" className="font-type flex border-b border-ink text-lg">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`flex-1 cursor-pointer whitespace-nowrap px-1 py-2 text-base ${tab === t.id ? 'bg-ink text-paper' : 'bg-transparent'}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {tab === 'sightings' && <SightingsList sightings={sightings} />}
        {tab === 'history' && <HistoryList history={history} />}
        {tab === 'suggest' && <SuggestForm nodeId={nodeId} onCited={onCited} />}
      </div>
    </aside>
  )
}

function SightingsList({ sightings }: { sightings: Sighting[] }) {
  // Defensive: the backend should never send a sighting that isn't nsfw === false, but
  // never render one that slips through anyway.
  const safe = sightings.filter((s) => s.nsfw === false)
  if (safe.length === 0) return <p className="font-type text-lg">No recent sightings of this meme.</p>
  return (
    <ul className="m-0 list-none space-y-3 p-0">
      {safe.map((s) => (
        <li key={s.id} className="flex gap-3">
          <img src={s.image_url} alt="" loading="lazy" className="h-20 w-20 shrink-0 border border-ink object-cover" />
          <div className="min-w-0">
            <a href={s.post_url} target="_blank" rel="noopener noreferrer" className="line-clamp-2 text-lg font-bold leading-tight">
              {s.title}
            </a>
            <div className="font-type text-sm">
              {timeAgo(s.posted_at)} on {s.platform}
              {s.author ? ` · ${s.author}` : ''}
            </div>
          </div>
        </li>
      ))}
    </ul>
  )
}

function HistoryList({ history }: { history: HistoryItem[] }) {
  if (history.length === 0) return <p className="font-type text-lg">Nothing recorded yet.</p>
  return (
    <ol className="m-0 list-none space-y-3 p-0">
      {history.map((h) => (
        <li key={h.id} className="border-b border-dashed border-ink-soft pb-2">
          <div className="font-type flex items-center gap-2 text-sm uppercase">
            <span>{HISTORY_LABEL[h.type]}</span>
            <span>{new Date(h.ts).toLocaleDateString('en', { day: 'numeric', month: 'short', year: 'numeric' })}</span>
            {h.pending && <span className="-rotate-2 border-2 border-stamp px-1 text-stamp">pending</span>}
          </div>
          <p className="m-0 text-base leading-snug">{h.message}</p>
          {h.source_url && (
            <a href={h.source_url} target="_blank" rel="noopener noreferrer" className="font-type text-sm underline">
              source
            </a>
          )}
        </li>
      ))}
    </ol>
  )
}

function SuggestForm({ nodeId, onCited }: { nodeId: string; onCited: (link: Link) => void }) {
  const [url, setUrl] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<ProposalResponse>()
  const [error, setError] = useState<string>()

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(undefined)
    setResult(undefined)
    try {
      const response = await propose(nodeId, url.trim(), note.trim())
      setResult(response)
      if (response.accepted && response.link) onCited(response.link)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const field = 'w-full border border-ink bg-paper px-2 py-1.5 text-base'
  return (
    <form onSubmit={submit} className="space-y-3">
      <p className="m-0 text-base leading-snug">
        Know a page that describes where this meme comes from? If it contains a sentence naming both memes, the link becomes cited.
      </p>
      <label className="font-type block text-sm uppercase">
        Page URL
        <input type="url" required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" className={field} />
      </label>
      <label className="font-type block text-sm uppercase">
        Note
        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} className={field} />
      </label>
      <button
        type="submit"
        disabled={busy || url.trim() === ''}
        className="font-type cursor-pointer border-2 border-ink bg-ink px-4 py-1.5 text-lg text-paper disabled:cursor-wait disabled:opacity-50"
      >
        {busy ? 'Checking the page…' : 'Submit'}
      </button>
      {error && <p className="m-0 text-stamp">Could not submit: {error}</p>}
      {result && (
        <div className={`border-2 p-2 ${result.accepted ? 'border-cited' : 'border-stamp'}`}>
          <p className="m-0 text-base font-bold">{result.accepted ? 'Accepted' : 'Not accepted'}</p>
          <p className="m-0 text-base leading-snug">{result.message}</p>
        </div>
      )}
    </form>
  )
}
