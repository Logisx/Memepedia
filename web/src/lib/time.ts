import type { MemeNode } from '@contract/types'

/** "just now", "6 min ago", "3 h ago", "2 d ago". */
export function timeAgo(iso: string, now: number = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000))
  if (seconds < 45) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}

/** The year a meme was first recorded, e.g. "2018", or null when unknown. */
export function firstSeenYear(node: Pick<MemeNode, 'first_seen'>): string | null {
  return node.first_seen ? (node.first_seen.split('-')[0] ?? null) : null
}

/** Show a first-seen date only as precisely as `date_precision` allows. */
export function formatFirstSeen(node: Pick<MemeNode, 'first_seen' | 'date_precision'>): string | null {
  if (!node.first_seen) return null
  const [year = '', month = '', day = ''] = node.first_seen.split('-')
  if (node.date_precision === 'year' || node.date_precision === null) return year
  const monthName = new Date(Date.UTC(Number(year), Number(month) - 1, 1)).toLocaleString('en', {
    month: 'long',
    timeZone: 'UTC',
  })
  if (node.date_precision === 'month') return `${monthName} ${year}`
  return `${Number(day)} ${monthName} ${year}`
}
