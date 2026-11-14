import { useState } from 'react'
import { motion } from 'motion/react'
import { Link as RouterLink } from 'react-router'
import type { Platform, Sighting } from '@contract/types'
import { timeAgo } from '../lib/time'

const PLATFORM_NAME: Record<Platform, string> = {
  lemmy: 'Lemmy',
  reddit: 'Reddit',
  imgflip: 'Imgflip',
  mastodon: 'Mastodon',
  x: 'X',
}

function Stamp({ sighting }: { sighting: Sighting }) {
  if (sighting.state === 'resolved') {
    return (
      <span className="font-type absolute left-2 top-2 -rotate-3 border-2 border-stamp bg-paper px-2 py-0.5 text-lg uppercase text-stamp">
        family: {sighting.node_name ?? sighting.node_id}
      </span>
    )
  }
  if (sighting.state === 'pending') {
    return (
      <span className="font-type absolute left-2 top-2 -rotate-3 border-2 border-dashed border-ink bg-paper px-2 py-0.5 text-lg uppercase">
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

  const picture = broken ? (
    <div className="font-type flex aspect-[4/3] items-center justify-center bg-paper-deep p-3 text-center text-lg">
      image unavailable
    </div>
  ) : (
    <img
      src={sighting.image_url}
      alt={sighting.title}
      loading="lazy"
      onError={() => setBroken(true)}
      className="block w-full bg-paper-deep"
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
      <div className="p-3">
        <a
          href={sighting.post_url}
          target="_blank"
          rel="noopener noreferrer"
          className="line-clamp-3 text-xl font-bold leading-tight no-underline hover:underline"
        >
          {sighting.title}
        </a>
        <div className="font-type mt-1 text-base">
          spotted {timeAgo(sighting.posted_at, now)} on {PLATFORM_NAME[sighting.platform]}
        </div>
      </div>
    </motion.article>
  )
}
