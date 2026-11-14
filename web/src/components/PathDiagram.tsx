import { Fragment } from 'react'
import { Link as RouterLink } from 'react-router'
import type { AncestorPath, MemeNode } from '@contract/types'
import { abbreviateLatin } from '../lib/latin'
import { firstSeenYear } from '../lib/time'
import { NodeThumb } from './SpecimenCard'

function PathNode({ node, ancestor = false }: { node: MemeNode; ancestor?: boolean }) {
  const year = firstSeenYear(node)
  return (
    <RouterLink
      to={`/meme/${node.id}`}
      className={`flex w-56 shrink-0 items-center gap-2 bg-paper p-1.5 no-underline ${ancestor ? 'border-4 border-stamp' : 'border-2 border-ink'}`}
    >
      <NodeThumb node={node} className="h-14 w-14" />
      <span className="min-w-0">
        <span className="line-clamp-2 block text-lg font-extrabold leading-tight">{node.name}</span>
        {node.latin_name && <span className="block truncate text-base italic leading-tight">{abbreviateLatin(node.latin_name)}</span>}
        <span className="font-type block text-sm">{year ? `first recorded ${year}` : 'date unknown'}</span>
      </span>
    </RouterLink>
  )
}

function Row({ ids, ancestorId, nodes }: { ids: string[]; ancestorId: string; nodes: Map<string, MemeNode> }) {
  // The common ancestor is drawn once, on the right; leave it off the row if the path already ends there.
  const shown = ids.filter((id) => id !== ancestorId).flatMap((id) => nodes.get(id) ?? [])
  return (
    <div className="flex items-center gap-2">
      {shown.map((node, i) => (
        <Fragment key={node.id}>
          {i > 0 && <span aria-hidden className="text-2xl">→</span>}
          <PathNode node={node} />
        </Fragment>
      ))}
    </div>
  )
}

interface Props {
  title: string
  path: AncestorPath
  nodes: Map<string, MemeNode>
}

/** Two paths, one per meme, that meet at their common ancestor. */
export function PathDiagram({ title, path, nodes }: Props) {
  const ancestor = nodes.get(path.ancestor_id)
  return (
    <section className="w-fit max-w-full border-2 border-ink p-4">
      <h2 className="font-type m-0 mb-3 text-lg uppercase tracking-widest">{title}</h2>
      <div className="flex items-stretch gap-3 overflow-x-auto pb-2">
        <div className="flex flex-col justify-center gap-6">
          <Row ids={path.path_a} ancestorId={path.ancestor_id} nodes={nodes} />
          <Row ids={path.path_b} ancestorId={path.ancestor_id} nodes={nodes} />
        </div>
        <div aria-hidden className="w-8 shrink-0 border-y-2 border-r-2 border-ink" />
        <div className="flex flex-col items-start justify-center gap-1">
          <span className="font-type text-sm uppercase text-stamp">common ancestor</span>
          {ancestor ? <PathNode node={ancestor} ancestor /> : <span className="text-xl">{path.ancestor_id}</span>}
        </div>
      </div>
    </section>
  )
}
