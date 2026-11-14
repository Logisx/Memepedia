import { useCallback } from 'react'
import { useSearchParams } from 'react-router'
import { Raw } from '../components/Raw'
import { getRelated } from '../data'

export default function Related() {
  const [params] = useSearchParams()
  const a = params.get('a') ?? 'doomer'
  const b = params.get('b') ?? 'yes-chad'
  const load = useCallback(() => getRelated(a, b), [a, b])
  return <Raw label={`GET /api/related?a=${a}&b=${b}`} load={load} />
}
