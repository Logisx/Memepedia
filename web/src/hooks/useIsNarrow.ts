import { useSyncExternalStore } from 'react'

/** Matches Tailwind's `lg` breakpoint: below it the meme page stacks its sections. */
const NARROW = '(max-width: 1023px)'

function subscribe(onChange: () => void): () => void {
  const query = window.matchMedia(NARROW)
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}

/** True on phones and tablets, and updates when the window is resized or rotated. */
export function useIsNarrow(): boolean {
  return useSyncExternalStore(subscribe, () => window.matchMedia(NARROW).matches, () => false)
}
