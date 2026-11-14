import { useCallback, useEffect, useRef, useState } from 'react'
import { ImageDrop } from '../components/ImageDrop'
import { SearchBox } from '../components/SearchBox'
import { SightingTile } from '../components/SightingTile'
import { WeekStrip } from '../components/WeekStrip'
import { getOlderWall, getWall } from '../data'
import { useColumnCount } from '../hooks/useColumnCount'
import { useNow } from '../hooks/useNow'
import { usePolling } from '../hooks/usePolling'
import { useShowSensitive } from '../hooks/useShowSensitive'
import { addSightings, appendOlder, emptyMasonry, relayout, type MasonryState } from '../lib/masonry'

const POLL_MS = 5_000
const OLDER_PAGE_SIZE = 60

export default function Wall() {
  const now = useNow()
  const count = useColumnCount()
  const showSensitive = useShowSensitive()
  const [masonry, setMasonry] = useState<MasonryState>(emptyMasonry)
  const [sources, setSources] = useState<number>()
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string>()
  const since = useRef<string>(undefined)
  const arrived = useRef(new Set<string>()) // ids that came in after the first load
  const countRef = useRef(count)

  // Older pages, loaded as the viewer scrolls down. Independent of the live `since` poll above:
  // `nextBefore` is seeded once from the first poll and only moves forward as older pages load.
  const [nextBefore, setNextBefore] = useState<string>()
  const [olderDone, setOlderDone] = useState(false)
  const [loadingOlder, setLoadingOlder] = useState(false)
  const [olderError, setOlderError] = useState<string>()
  const seededOlder = useRef(false)
  const sentinelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    countRef.current = count
    setMasonry((prev) => (prev.columns.length === count ? prev : relayout(prev, count)))
  }, [count])

  // Toggling "show sensitive" changes what the feed should ask for; wipe what's shown and
  // restart polling (via resetKey) so it takes effect immediately, not on the next 5s tick.
  useEffect(() => {
    since.current = undefined
    arrived.current = new Set()
    setMasonry(emptyMasonry())
    setLoaded(false)
    seededOlder.current = false
    setNextBefore(undefined)
    setOlderDone(false)
    setOlderError(undefined)
  }, [showSensitive])

  usePolling(
    async () => {
      try {
        const wall = await getWall(since.current, 60, showSensitive)
        if (since.current !== undefined) wall.sightings.forEach((s) => arrived.current.add(s.id))
        since.current = wall.server_time
        setMasonry((prev) => addSightings(prev, wall.sightings, countRef.current))
        setSources(wall.sources_watched)
        setLoaded(true)
        setError(undefined)
        // Seed the older-pages cursor once, from the first poll only; later polls only
        // ever reveal newer sightings and must not move it back toward the present.
        if (!seededOlder.current) {
          seededOlder.current = true
          setNextBefore(wall.next_before ?? undefined)
          setOlderDone(wall.next_before === null)
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      }
    },
    POLL_MS,
    showSensitive,
  )

  const loadOlder = useCallback(async () => {
    if (loadingOlder || olderDone || !nextBefore) return
    setLoadingOlder(true)
    try {
      const wall = await getOlderWall(nextBefore, OLDER_PAGE_SIZE, showSensitive)
      setMasonry((prev) => appendOlder(prev, wall.sightings))
      setNextBefore(wall.next_before ?? undefined)
      setOlderDone(wall.next_before === null)
      setOlderError(undefined)
    } catch (e) {
      setOlderError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoadingOlder(false)
    }
  }, [loadingOlder, olderDone, nextBefore, showSensitive])

  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void loadOlder()
      },
      { rootMargin: '800px 0px' },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [loadOlder])

  return (
    <div className="px-6 py-4">
      <div className="mb-4 flex flex-wrap items-stretch gap-4">
        <SearchBox />
        <ImageDrop />
      </div>
      <WeekStrip />

      <p className="font-type my-3 flex items-center gap-2 text-lg" aria-live="polite">
        <span className={`inline-block h-3 w-3 rounded-full ${error ? 'bg-stamp' : 'animate-pulse bg-cited'}`} />
        {error
          ? `Lost the connection (${error}); retrying…`
          : sources === undefined
            ? 'Listening…'
            : `watching ${sources} sources`}
      </p>

      {loaded && masonry.byId.size === 0 && (
        <p className="font-type text-xl">Nothing spotted yet. The wall fills as new posts are seen.</p>
      )}
      <div className="flex items-start gap-4">
        {masonry.columns.map((column, i) => (
          <div key={i} className="min-w-0 flex-1">
            {column.map((id) => {
              const sighting = masonry.byId.get(id)
              return sighting ? (
                <SightingTile key={id} sighting={sighting} now={now} arriving={arrived.current.has(id)} />
              ) : null
            })}
          </div>
        ))}
      </div>

      {loaded && masonry.byId.size > 0 && <div ref={sentinelRef} aria-hidden="true" className="h-1" />}
      {loadingOlder && <p className="font-type my-4 text-center text-lg">loading older posts…</p>}
      {olderError && !loadingOlder && (
        <button
          type="button"
          onClick={() => void loadOlder()}
          className="font-type my-4 block w-full text-center text-lg text-stamp underline"
        >
          Couldn't load older posts ({olderError}); tap to retry.
        </button>
      )}
      {olderDone && !loadingOlder && masonry.byId.size > 0 && (
        <p className="font-type my-4 text-center text-lg text-ink-soft">That's the whole wall.</p>
      )}
    </div>
  )
}
