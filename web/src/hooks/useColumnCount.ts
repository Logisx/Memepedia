import { useEffect, useState } from 'react'

/** How many wall columns fit: 2 on small screens, 3 from 1024px, 5 from 1536px. */
function columnsFor(width: number): number {
  if (width >= 1536) return 5
  if (width >= 1024) return 3
  return 2
}

export function useColumnCount(): number {
  const [count, setCount] = useState(() => columnsFor(window.innerWidth))
  useEffect(() => {
    const onResize = () => setCount(columnsFor(window.innerWidth))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  return count
}
