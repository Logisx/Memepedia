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
  const formatChips = useMemo(
    () =>
      tree.links
        .filter((l) => l.axis === 'format' && l.child_id === tree.selected_id)
        .flatMap((l) => {
          const parent = nodesById.get(l.parent_id)
          return parent ? [{ link: l, parent }] : []
        }),
    [tree.links, tree.selected_id, nodesById],
  )

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

  return (
    <div className="flex h-[calc(100vh-4.25rem)] min-h-[34rem] flex-col">
      <section className="flex h-[45%] min-h-0 flex-col px-6 pt-3">
        <div className="font-type flex flex-wrap items-center gap-x-6 gap-y-1 pb-2 text-lg">
          <span className="text-2xl font-bold">{selected?.name ?? tree.selected_id}</span>
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
        <div className="min-h-0 flex-1">
          <DescentStrip axis={axis} descent={tree.descent[axis]} nodesById={nodesById} links={tree.links} />
        </div>
      </section>

      <section className="flex h-[55%] min-h-0 border-t border-ink">
        <motion.div
          className="min-w-0 flex-1"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: mapDelay, duration: 0.6 }}
        >
          <FamilyMap tree={tree} />
        </motion.div>
        <SidePanel nodeId={tree.selected_id} sightings={tree.sightings} history={tree.history} onCited={markCited} />
      </section>
    </div>
  )
}
