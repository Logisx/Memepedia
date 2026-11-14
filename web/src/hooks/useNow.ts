import { useEffect, useState } from 'react'

/** The current time in ms, refreshed every `intervalMs`, so "6 min ago" labels keep ticking. */
export function useNow(intervalMs = 15_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs])
  return now
}
