import { useState } from 'react'
import { motion } from 'motion/react'
import { Link as RouterLink } from 'react-router'
import type { Sighting } from '@contract/types'
import { PLATFORM_NAME } from '../lib/platform'
import { timeAgo } from '../lib/time'

/** Scraped titles carry site boilerplate; drop it. */
function cleanTitle(title: string): string {
  return title
    .replace(/\s*\|\s*made w\/\s*imgflip meme maker/i, '')
    .replace(/^image tagged in\s+/i, 'tagged: ')
    .replace(/;\s*/g, ' · ')
    .trim()
}

function Stamp({ sighting }: { sighting: Sighting }) {
  if (sighting.state === 'resolved') {
    return (
      <span className="font-type absolute bottom-0 left-2 z-10 translate-y-1/2 -rotate-2 border-2 border-stamp bg-paper px-2 py-0.5 text-lg uppercase text-stamp">
        family: {sighting.node_name ?? sighting.node_id}
      </span>
    )
  }
  if (sighting.state === 'pending') {
    return (
      <span className="font-type absolute bottom-0 left-2 z-10 translate-y-1/2 -rotate-2 border-2 border-dashed border-ink bg-paper px-2 py-0.5 text-lg uppercase">
        unidentified
      </span>
    )
  }
  return null // unclassified posts carry no stamp
}

interface Props {
  sighting: Sighting
  now: number
  /** True for tiles that arrive after the first load: they animate in. */
  arriving: boolean
}

/** One post seen in the wild, stamped with the family it belongs to. */
export function SightingTile({ sighting, now, arriving }: Props) {
  const [broken, setBroken] = useState(false)
  const resolved = sighting.state === 'resolved' && sighting.node_id !== null

  // Defensive: the backend should never send a sighting that isn't nsfw === false, but
  // never render one that slips through anyway.
  if (sighting.nsfw !== false) return null

  const picture = broken ? (
    <div className="font-type flex h-16 items-center justify-center bg-paper-deep p-3 text-center text-base text-ink-soft">
      specimen missing
    </div>
  ) : (
    <img
      src={sighting.image_url}
      alt={sighting.title}
      loading="lazy"
      onError={() => setBroken(true)}
      className={`block w-full bg-paper-deep ${sighting.state === 'unclassified' ? 'opacity-70 grayscale-[30%]' : ''}`}
    />
  )

  return (
    <motion.article
      className="mb-4 break-inside-avoid border-2 border-ink bg-paper shadow-[4px_4px_0_var(--color-ink)]"
      initial={arriving ? { opacity: 0, y: -24, scale: 0.96 } : false}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.5, ease: 'easeOut' }}
    >
      <div className="relative border-b-2 border-ink">
        {resolved ? (
          <RouterLink to={`/meme/${sighting.node_id}`} className="block" aria-label={`Open ${sighting.node_name ?? 'meme'}`}>
            {picture}
          </RouterLink>
        ) : (
          picture
        )}
        <Stamp sighting={sighting} />
      </div>
      <div className={`p-3 ${sighting.state === 'resolved' || sighting.state === 'pending' ? 'pt-5' : ''}`}>
        <a
          href={sighting.post_url}
          target="_blank"
          rel="noopener noreferrer"
          className="line-clamp-3 text-xl font-bold leading-tight no-underline hover:underline"
        >
          {cleanTitle(sighting.title)}
        </a>
        <div className="font-type mt-1 text-base">
          spotted {timeAgo(sighting.posted_at, now)} on {PLATFORM_NAME[sighting.platform]}
        </div>
      </div>
    </motion.article>
  )
}
