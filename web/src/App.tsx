import { BrowserRouter, Link, NavLink, Route, Routes } from 'react-router'
import { setShowSensitive, useShowSensitive } from './hooks/useShowSensitive'
import Lineage from './screens/Lineage'
import NotFound from './screens/NotFound'
import Related from './screens/Related'
import Trace from './screens/Trace'
import Wall from './screens/Wall'

function SensitiveToggle() {
  const showSensitive = useShowSensitive()
  return (
    <button
      type="button"
      aria-pressed={showSensitive}
      onClick={() => setShowSensitive(!showSensitive)}
      className="font-type ml-auto shrink-0 border border-ink px-2 py-1 text-sm uppercase tracking-widest hover:bg-paper-deep"
    >
      Sensitive: {showSensitive ? 'shown' : 'hidden'}
    </button>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <header className="flex flex-wrap items-baseline gap-6 border-b border-ink px-6 py-3">
        <Link to="/" className="text-3xl font-extrabold no-underline">
          Memepedia
        </Link>
        <nav className="font-type flex gap-6 text-xl">
          {[
            { to: '/', label: 'Wall', end: true },
            { to: '/related', label: 'Compare two memes', end: false },
          ].map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.end}
              className={({ isActive }) => `no-underline ${isActive ? 'border-b-2 border-ink font-bold' : 'border-b-2 border-transparent hover:border-ink-soft'}`}
            >
              {l.label}
            </NavLink>
          ))}
        </nav>
        <SensitiveToggle />
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Wall />} />
          <Route path="/meme/:id" element={<Lineage />} />
          <Route path="/trace" element={<Trace />} />
          <Route path="/related" element={<Related />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}
