import { useCallback, useEffect, useMemo, useState } from 'react'
import { motion } from 'motion/react'
import { Link as RouterLink, useParams } from 'react-router'
import type { Axis, Link, TreeResponse } from '@contract/types'
import { DescentStrip, flipDuration } from '../components/DescentStrip'
import { FamilyMap } from '../components/FamilyMap'
import { SidePanel } from '../components/SidePanel'
import { getTree } from '../data'

type Load = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; tree: TreeResponse }

/** Route wrapper: loads the tree for `/meme/:id`, then hands it to the view. */
export default function Lineage() {
  const { id = '' } = useParams()
  const [load, setLoad] = useState<Load>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoad({ status: 'loading' })
    getTree(id).then(
      (tree) => !cancelled && setLoad({ status: 'ready', tree }),
      (e: unknown) => !cancelled && setLoad({ status: 'error', message: e instanceof Error ? e.message : String(e) }),
    )
    return () => {
      cancelled = true
    }
  }, [id, attempt])

  if (load.status === 'loading') return <p className="font-type p-8 text-2xl">Opening the drawer…</p>
  if (load.status === 'error') {
    return (
      <div className="p-8">
        <p className="text-2xl text-stamp">Could not load this meme: {load.message}</p>
        <button onClick={() => setAttempt((n) => n + 1)} className="font-type mt-3 cursor-pointer border-2 border-ink px-4 py-1 text-xl">
          Try again
        </button>
      </div>
    )
  }
  return <LineageView key={id} initial={load.tree} />
}

function LineageView({ initial }: { initial: TreeResponse }) {
  const [tree, setTree] = useState(initial)
  const [axis, setAxis] = useState<Axis>('character')

  const nodesById = useMemo(() => new Map(tree.nodes.map((n) => [n.id, n])), [tree.nodes])
  const selected = nodesById.get(tree.selected_id)
  // A format parent already drawn in the visible line needs no extra chip.
  const formatChips = useMemo(() => {
    const visible = new Set(tree.descent[axis])
    return tree.links
      .filter((l) => l.axis === 'format' && l.child_id === tree.selected_id && !visible.has(l.parent_id))
      .flatMap((l) => {
        const parent = nodesById.get(l.parent_id)
        return parent ? [{ link: l, parent }] : []
      })
  }, [tree.links, tree.descent, axis, tree.selected_id, nodesById])

  // A proposal that earned a citation flips the matching link in place.
  const markCited = useCallback((updated: Link) => {
    setTree((prev) => ({
      ...prev,
      links: prev.links.map((l) =>
        l.child_id === updated.child_id && l.parent_id === updated.parent_id && l.axis === updated.axis ? updated : l,
      ),
    }))
  }, [])

  const mapDelay = flipDuration(tree.descent.character.length) + 0.2
  // When both lines are the same chain there is nothing to switch between.
  const linesDiffer = tree.descent.character.join('>') !== tree.descent.format.join('>')
  const aloneInFamily = tree.family_ids.length <= 1

  // Phones and tablets stack the sections and let the page scroll; from lg up it is one screen.
  return (
    <div className="flex flex-col lg:h-[calc(100dvh-4.25rem)] lg:min-h-[34rem]">
      <section className="flex flex-col px-4 pt-3 lg:h-[45%] lg:min-h-0 lg:px-6">
        <div className="font-type flex flex-wrap items-center gap-x-4 gap-y-2 pb-2 text-lg lg:gap-x-6 lg:gap-y-1">
          <span className="font-display min-w-0 break-words text-2xl font-extrabold lg:text-3xl">{selected?.name ?? tree.selected_id}</span>
          {linesDiffer && (
            <div role="group" aria-label="Line of descent" className="flex border-2 border-ink">
              {(['character', 'format'] as const).map((a) => (
                <button
                  key={a}
                  aria-pressed={axis === a}
                  onClick={() => setAxis(a)}
                  className={`cursor-pointer px-3 py-0.5 capitalize ${axis === a ? 'bg-ink text-paper' : 'bg-transparent'}`}
                >
                  {a} line
                </button>
              ))}
            </div>
          )}
          {formatChips.map(({ link, parent }) => (
            <RouterLink
              key={link.parent_id}
              to={`/meme/${parent.id}`}
              className={`border-2 px-2 py-0.5 no-underline ${link.status === 'cited' ? 'border-solid border-cited' : 'border-dashed border-ink-soft'}`}
            >
              format: {parent.name}
            </RouterLink>
          ))}
        </div>
        <div className="h-[24rem] lg:h-auto lg:min-h-0 lg:flex-1">
          <DescentStrip axis={axis} descent={tree.descent[axis]} nodesById={nodesById} links={tree.links} />
        </div>
      </section>

      <section className="flex flex-col border-t border-ink lg:h-[55%] lg:min-h-0 lg:flex-row">
        <motion.div
          className="relative h-[26rem] min-w-0 lg:h-auto lg:flex-1"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: mapDelay, duration: 0.6 }}
        >
          <FamilyMap tree={tree} />
          {aloneInFamily && (
            <p className="font-type pointer-events-none absolute inset-x-0 top-[calc(50%+4rem)] m-0 px-4 text-center text-lg text-ink-soft">
              No relatives on record yet: this meme is the only one in its family so far.
            </p>
          )}
        </motion.div>
        <SidePanel nodeId={tree.selected_id} sightings={tree.sightings} history={tree.history} onCited={markCited} />
      </section>
    </div>
  )
}
