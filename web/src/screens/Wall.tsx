import { Raw } from '../components/Raw'
import { getWall, getWeek } from '../data'

const loadWall = () => getWall()

export default function Wall() {
  return (
    <>
      <Raw label="GET /api/week" load={getWeek} />
      <Raw label="GET /api/wall" load={loadWall} />
    </>
  )
}
