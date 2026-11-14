import { useCallback } from 'react'
import { useParams } from 'react-router'
import { Raw } from '../components/Raw'
import { getTree } from '../data'

export default function Lineage() {
  const { id = '' } = useParams()
  const load = useCallback(() => getTree(id), [id])
  return <Raw label={`GET /api/tree/${id}`} load={load} />
}
