import type { Link } from '@contract/types'

/**
 * The link between two cards in the descent strip.
 * Cited: the verbatim quote and its source. Inferred: a dashed line marked "citation needed".
 */
export function LinkConnector({ link, checking = false }: { link: Link | undefined; checking?: boolean }) {
  const cited = link?.status === 'cited'
  return (
    <div className="flex h-full w-60 shrink-0 flex-col justify-center gap-2 px-2">
      {link && cited && (
        <>
          <span className="font-type text-sm uppercase tracking-widest text-cited">cited</span>
          <blockquote className="text-base italic leading-snug">“{link.quote}”</blockquote>
          {link.source_url && (
            <a
              href={link.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-type text-sm underline"
            >
              {link.source_title ?? link.source_url}
            </a>
          )}
        </>
      )}
      {link && !cited && checking && (
        <span className="font-type animate-pulse self-start border-2 border-dashed border-ink-soft px-2 py-0.5 text-lg uppercase">
          checking the web…
        </span>
      )}
      {link && !cited && !checking && (
        <span className="font-type -rotate-2 self-start border-2 border-dashed border-stamp px-2 py-0.5 text-lg uppercase text-stamp">
          citation needed
        </span>
      )}
      <div
        aria-hidden
        className={`relative border-t-2 ${cited ? 'border-solid border-cited' : 'border-dashed border-ink-soft'}`}
      >
        <span className="absolute -right-1 -top-[11px] text-lg leading-none">▸</span>
      </div>
    </div>
  )
}
