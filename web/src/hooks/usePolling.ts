import { useEffect, useRef } from 'react'

/** Call `tick` now and then every `intervalMs`, until unmount. Overlapping ticks are skipped. */
export function usePolling(tick: () => Promise<void>, intervalMs: number): void {
  const latest = useRef(tick)
  useEffect(() => {
    latest.current = tick
  })

  useEffect(() => {
    let running = false
    const run = async () => {
      if (running) return
      running = true
      try {
        await latest.current()
      } finally {
        running = false
      }
    }
    void run()
    const timer = setInterval(() => void run(), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs])
}
