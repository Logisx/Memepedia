import { useRef, useState } from 'react'
import { BrowserRouter, Link, NavLink, Route, Routes } from 'react-router'
import { setShowSensitive, useShowSensitive } from './hooks/useShowSensitive'
import Lineage from './screens/Lineage'
import NotFound from './screens/NotFound'
import Related from './screens/Related'
import Trace from './screens/Trace'
import Wall from './screens/Wall'

function SensitiveToggle() {
  const showSensitive = useShowSensitive()
  const [wiggling, setWiggling] = useState(false)
  const wiggleTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  const toggle = () => {
    setShowSensitive(!showSensitive)
    setWiggling(true)
    clearTimeout(wiggleTimer.current)
    wiggleTimer.current = setTimeout(() => setWiggling(false), 400)
  }

  return (
    <button
      type="button"
      aria-pressed={showSensitive}
      aria-label={showSensitive ? 'NSFW is on: switch to SFW' : 'SFW is on: switch to NSFW'}
      title={showSensitive ? 'Showing NSFW. Click to go back to SFW' : 'SFW only. Click to show NSFW'}
      onClick={toggle}
      className="font-type ml-auto flex min-w-[7rem] shrink-0 items-center justify-center gap-2 border-2 border-ink px-4 py-2 text-base uppercase tracking-widest hover:bg-paper-deep md:text-lg"
    >
      <span
        aria-hidden
        className={`text-2xl md:text-3xl ${wiggling ? 'animate-emoji-wiggle inline-block' : 'inline-block'}`}
      >
        {showSensitive ? '👀' : '🙈'}
      </span>
      {showSensitive ? 'NSFW' : 'SFW'}
    </button>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <header className="flex flex-wrap items-baseline gap-x-4 gap-y-2 border-b border-ink px-4 py-3 md:gap-6 md:px-6">
        <Link to="/" className="text-2xl font-extrabold no-underline md:text-3xl">
          Memepedia
        </Link>
        <nav className="font-type flex gap-4 text-lg md:gap-6 md:text-xl">
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
