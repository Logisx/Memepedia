import { Fragment, useEffect, useRef } from 'react'
import { motion } from 'motion/react'
import { Link as RouterLink } from 'react-router'
import type { Axis, Link, MemeNode } from '@contract/types'
import { useIsNarrow } from '../hooks/useIsNarrow'
import { LinkConnector } from './LinkConnector'
import { SpecimenCard } from './SpecimenCard'

const FLIP_STEP_S = 0.35

/** Seconds the whole flip-in takes for a strip of `count` cards. */
export function flipDuration(count: number): number {
  return Math.max(0, count - 1) * FLIP_STEP_S + 0.6
}

interface Props {
  axis: Axis
  /** Node ids from the selected meme back to the root, as the API returns them. */
  descent: string[]
  nodesById: Map<string, MemeNode>
  links: Link[]
  /** While a trace is running, inferred links read "checking the web…" instead of "citation needed". */
  checking?: boolean
}

/** The line of descent: oldest on the left, the selected meme on the right. */
export function DescentStrip({ axis, descent, nodesById, links, checking = false }: Props) {
  const ordered = [...descent].reverse() // oldest first
  const count = ordered.length
  const narrow = useIsNarrow()
  const scroller = useRef<HTMLDivElement>(null)
  const chain = descent.join('>')

  // On a phone the strip is wider than the screen and the selected meme is its last card:
  // start at that end instead of on the oldest ancestor.
  useEffect(() => {
    const el = scroller.current
    if (narrow && el) el.scrollLeft = el.scrollWidth
  }, [narrow, chain])

  if (count === 0) {
    return <p className="font-type self-center p-4 text-xl">No recorded {axis} line for this meme.</p>
  }

  return (
    <div ref={scroller} className="flex h-full items-stretch overflow-x-auto pb-3 pr-3 pt-1">
      {ordered.map((id, index) => {
        const node = nodesById.get(id)
        if (!node) return null
        const rank = count - 1 - index // 0 = the selected meme, which flips in first
        const delay = rank * FLIP_STEP_S
        const olderId = ordered[index - 1]
        // Prefer a link on this axis; the API can list a parent in this line that is joined by a link on the other axis.
        const between = olderId ? links.filter((l) => l.child_id === id && l.parent_id === olderId) : []
        const link = between.find((l) => l.axis === axis) ?? between[0]
        return (
          <Fragment key={`${axis}:${id}`}>
            {index > 0 && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: delay + 0.25, duration: 0.4 }}
              >
                <LinkConnector link={link} checking={checking} />
              </motion.div>
            )}
            <motion.div
              className="h-full w-56 shrink-0"
              style={{ perspective: 900 }}
              initial={{ rotateY: -95, opacity: 0 }}
              animate={{ rotateY: 0, opacity: 1 }}
              transition={{ delay, duration: 0.55, ease: 'easeOut' }}
            >
              <RouterLink to={`/meme/${node.id}`} className="block h-full no-underline" aria-label={node.name}>
                <SpecimenCard node={node} selected={rank === 0} />
              </RouterLink>
            </motion.div>
          </Fragment>
        )
      })}
    </div>
  )
}
