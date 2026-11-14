import { useState } from 'react'
import type { MemeNode } from '@contract/types'
import { firstSeenYear } from '../lib/time'

const KIND_LABEL: Record<MemeNode['kind'], string> = {
  character: 'Character',
  template: 'Template',
  phrase: 'Phrase',
  format_class: 'Format class',
}

/** Small square thumbnail with a typeset initial when there is no usable image. */
export function NodeThumb({ node, className = 'h-14 w-14' }: { node: MemeNode; className?: string }) {
  const [broken, setBroken] = useState(false)
  if (node.image_url && !broken) {
    return (
      <img
        src={node.image_url}
        alt=""
        loading="lazy"
        onError={() => setBroken(true)}
        className={`${className} shrink-0 border border-ink bg-paper-deep object-cover`}
      />
    )
  }
  return (
    <span
      aria-hidden
      className={`${className} flex shrink-0 items-center justify-center border border-ink bg-paper-deep text-2xl font-extrabold`}
    >
      {node.name.charAt(0)}
    </span>
  )
}

/**
 * A pinned specimen: image above a museum label (name, Latin name, first recorded).
 * Without an image it becomes a typeset card that carries the same facts in large type.
 */
export function SpecimenCard({ node, selected = false }: { node: MemeNode; selected?: boolean }) {
  const [broken, setBroken] = useState(false)
  const hasImage = node.image_url !== null && !broken
  const year = firstSeenYear(node)
  const frame = `flex h-full w-full flex-col border-2 bg-paper p-2 ${
    selected ? 'border-stamp shadow-[4px_4px_0_var(--color-stamp)]' : 'border-ink shadow-[4px_4px_0_var(--color-ink)]'
  }`

  if (!hasImage) {
    return (
      <figure className={frame}>
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center border border-ink px-3 py-2 text-center">
          <span className="font-type text-sm uppercase tracking-widest text-ink-soft">{KIND_LABEL[node.kind]}</span>
          <span className="mt-1 text-3xl font-extrabold leading-tight">{node.name}</span>
          {node.latin_name && <span className="mt-1 text-lg italic">{node.latin_name}</span>}
        </div>
        <figcaption className="font-type pt-2 text-base">{year ? `first recorded ${year}` : 'date unknown'}</figcaption>
      </figure>
    )
  }

  return (
    <figure className={frame}>
      <div className="relative min-h-0 flex-1 border border-ink bg-paper-deep">
        <img
          src={node.image_url ?? undefined}
          alt={node.name}
          onError={() => setBroken(true)}
          className="absolute inset-0 h-full w-full object-contain"
        />
        {node.status === 'specimen' && (
          <span className="font-type absolute right-1 top-1 rotate-6 border-2 border-stamp bg-paper px-1 text-sm uppercase text-stamp">
            specimen
          </span>
        )}
      </div>
      <figcaption className="pt-2">
        <div className="text-xl font-extrabold leading-tight">{node.name}</div>
        {node.latin_name && <div className="text-base italic leading-tight">{node.latin_name}</div>}
        <div className="font-type text-sm">{year ? `first recorded ${year}` : 'date unknown'}</div>
      </figcaption>
    </figure>
  )
}
