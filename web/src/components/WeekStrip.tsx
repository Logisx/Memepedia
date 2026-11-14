import { useEffect, useState } from 'react'
import { Link as RouterLink } from 'react-router'
import type { WeekResponse } from '@contract/types'
import { getWeek } from '../data'
import { abbreviateLatin } from '../lib/latin'
import { NodeThumb } from './SpecimenCard'

const SPECIMENS_SHOWN = 6

/** "This week in memes": families rising against their six-day mean, and new specimens. */
export function WeekStrip() {
  const [week, setWeek] = useState<WeekResponse>()
  const [failed, setFailed] = useState(false)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    let cancelled = false
    getWeek().then(
      (w) => !cancelled && setWeek(w),
      () => !cancelled && setFailed(true),
    )
    return () => {
      cancelled = true
    }
  }, [])

  // A meme that is already rising does not need a second chip as a new specimen.
  const risingIds = new Set(week?.rising.map((r) => r.node.id))
  const specimens = week?.new_specimens.filter((n) => !risingIds.has(n.id)) ?? []
  const visibleSpecimens = showAll ? specimens : specimens.slice(0, SPECIMENS_SHOWN)
  const hiddenCount = specimens.length - visibleSpecimens.length
  const empty = week && week.rising.length === 0 && specimens.length === 0

  return (
    <section className="border-y border-ink py-3">
      <h2 className="font-type m-0 mb-2 text-lg uppercase tracking-widest">This week in memes</h2>
      {failed && <p className="font-type m-0 text-stamp">The weekly summary is unavailable right now.</p>}
      {!week && !failed && <p className="font-type m-0">Counting…</p>}
      {empty && <p className="font-type m-0">Nothing has moved yet this week.</p>}
      {week && !empty && (
        <div className="flex flex-col gap-3">
          {week.rising.length > 0 && (
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-type w-28 text-sm uppercase">Rising today</span>
              {week.rising.map(({ node, count_24h, daily_mean_prior }) => (
                <RouterLink
                  key={node.id}
                  to={`/meme/${node.id}`}
                  className="flex items-center gap-2 border-2 border-ink px-2 py-1 no-underline"
                >
                  <NodeThumb node={node} className="h-12 w-12" />
                  <span>
                    <span className="block text-xl font-extrabold leading-tight">▲ {node.name}</span>
                    <span className="font-type block text-sm">
                      {daily_mean_prior < 1
                        ? `${count_24h} today · first sightings`
                        : `${count_24h} today · usually ${Math.round(daily_mean_prior * 10) / 10}/day`}
                    </span>
                  </span>
                </RouterLink>
              ))}
            </div>
          )}
          {specimens.length > 0 && (
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-type w-28 text-sm uppercase">New specimens</span>
              {visibleSpecimens.map((node) => (
                <RouterLink
                  key={node.id}
                  to={`/meme/${node.id}`}
                  className="flex items-center gap-2 border-2 border-dashed border-stamp px-2 py-1 no-underline"
                >
                  <NodeThumb node={node} className="h-12 w-12" />
                  <span>
                    <span className="block text-xl font-bold leading-tight">{node.name}</span>
                    {node.latin_name && node.latin_name !== node.name && (
                      <span className="block text-base italic leading-tight">{abbreviateLatin(node.latin_name)}</span>
                    )}
                  </span>
                </RouterLink>
              ))}
              {specimens.length > SPECIMENS_SHOWN && (
                <button
                  type="button"
                  onClick={() => setShowAll((v) => !v)}
                  className="font-type cursor-pointer border-2 border-dashed border-ink bg-paper px-3 py-3 text-lg"
                >
                  {showAll ? 'show fewer' : `+${hiddenCount} more`}
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
