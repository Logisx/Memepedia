import { useState } from 'react'
import type { MemeNode } from '@contract/types'
import { firstSeenYear } from '../lib/time'

const KIND_LABEL: Record<MemeNode['kind'], string> = {
  character: 'Character',
  template: 'Template',
  phrase: 'Phrase',
  format_class: 'Format class',
}

/** Not yet cleared (true) or not yet labelled (null): blur it until a click reveals it. */
function isSensitive(node: MemeNode): boolean {
  return node.nsfw !== false
}

/** Blurs an image behind a click-to-reveal overlay; stops the click from bubbling to a parent
 * link or button so revealing a thumbnail never also navigates or fires another action. */
function RevealOverlay({ onReveal, compact }: { onReveal: () => void; compact?: boolean }) {
  const reveal = (e: { preventDefault: () => void; stopPropagation: () => void }) => {
    e.preventDefault()
    e.stopPropagation()
    onReveal()
  }
  return (
    <span
      role="button"
      tabIndex={0}
      onClick={reveal}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && reveal(e)}
      aria-label="Sensitive image — click to show"
      className={`font-type absolute inset-0 flex cursor-pointer items-center justify-center bg-ink/70 text-center uppercase text-paper ${
        compact ? 'text-[9px] leading-tight' : 'text-sm'
      }`}
    >
      {compact ? 'Sensitive' : 'Sensitive — click to show'}
    </span>
  )
}

/** Small square thumbnail with a typeset initial when there is no usable image. */
export function NodeThumb({ node, className = 'h-14 w-14' }: { node: MemeNode; className?: string }) {
  const [broken, setBroken] = useState(false)
  const [revealed, setRevealed] = useState(false)
  const sensitive = isSensitive(node) && !revealed
  if (node.image_url && !broken) {
    return (
      <span className={`${className} relative block shrink-0 overflow-hidden border border-ink bg-paper-deep`}>
        <img
          src={node.image_url}
          alt=""
          loading="lazy"
          onError={() => setBroken(true)}
          className={`h-full w-full object-cover ${sensitive ? 'blur-sm' : ''}`}
        />
        {sensitive && <RevealOverlay onReveal={() => setRevealed(true)} compact />}
      </span>
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
  const [revealed, setRevealed] = useState(false)
  const sensitive = isSensitive(node) && !revealed
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
          className={`absolute inset-0 h-full w-full object-contain ${sensitive ? 'blur-md' : ''}`}
        />
        {sensitive && <RevealOverlay onReveal={() => setRevealed(true)} />}
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
