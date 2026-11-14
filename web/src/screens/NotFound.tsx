import { Link as RouterLink } from 'react-router'

export default function NotFound() {
  return (
    <div className="p-8">
      <h1 className="m-0 text-4xl font-extrabold">Page not found</h1>
      <p className="font-type mt-2 text-xl">There is no page at this address, and no specimen filed under it.</p>
      <RouterLink to="/" className="font-type text-xl">
        ← Back to the wall
      </RouterLink>
    </div>
  )
}
