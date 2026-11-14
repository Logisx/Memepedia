import { useEffect, useState } from 'react'
import { Link as RouterLink } from 'react-router'
import type { WeekResponse } from '@contract/types'
import { getWeek } from '../data'
import { NodeThumb } from './SpecimenCard'

/** "This week in memes": families rising against their six-day mean, and new specimens. */
export function WeekStrip() {
  const [week, setWeek] = useState<WeekResponse>()
  const [failed, setFailed] = useState(false)

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

  const empty = week && week.rising.length === 0 && week.new_specimens.length === 0

  return (
    <section className="border-y border-ink py-3">
      <h2 className="font-type m-0 mb-2 text-lg uppercase tracking-widest">This week in memes</h2>
      {failed && <p className="font-type m-0 text-stamp">The weekly summary is unavailable right now.</p>}
      {!week && !failed && <p className="font-type m-0">Counting…</p>}
      {empty && <p className="font-type m-0">Nothing has moved yet this week.</p>}
      {week && !empty && (
        <div className="flex flex-wrap gap-x-8 gap-y-3">
          {week.rising.length > 0 && (
            <div className="flex flex-wrap gap-3">
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
                      {count_24h} today · usually {Math.round(daily_mean_prior * 10) / 10}/day
                    </span>
                  </span>
                </RouterLink>
              ))}
            </div>
          )}
          {week.new_specimens.length > 0 && (
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-type text-sm uppercase">New specimens</span>
              {week.new_specimens.map((node) => (
                <RouterLink
                  key={node.id}
                  to={`/meme/${node.id}`}
                  className="flex items-center gap-2 border-2 border-dashed border-stamp px-2 py-1 no-underline"
                >
                  <NodeThumb node={node} className="h-12 w-12" />
                  <span className="text-xl font-bold italic">{node.latin_name ?? node.name}</span>
                </RouterLink>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
