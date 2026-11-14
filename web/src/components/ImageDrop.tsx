import { useRef, useState, type DragEvent } from 'react'
import { useNavigate } from 'react-router'
import { identify } from '../data'

/** Drop an image: open the meme it matches, or start a trace when it is unknown. */
export function ImageDrop() {
  const navigate = useNavigate()
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string>()

  async function handle(file: File | undefined) {
    if (!file) return
    if (!file.type.startsWith('image/')) {
      setMessage('That is not an image file.')
      return
    }
    setBusy(true)
    setMessage(undefined)
    try {
      const result = await identify(file)
      if (result.node_id) navigate(`/meme/${result.node_id}`)
      else if (result.trace_query) navigate(`/trace?q=${encodeURIComponent(result.trace_query)}`)
      else setMessage('Could not tell what this is. Try another image.')
    } catch (err) {
      setMessage(`Could not read the image: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setBusy(false)
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault()
    setOver(false)
    void handle(e.dataTransfer.files[0])
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={`font-type flex min-w-64 cursor-pointer flex-col items-center justify-center border-2 border-dashed border-ink px-4 py-2 text-center text-lg ${over ? 'bg-paper-deep' : ''}`}
      role="button"
      tabIndex={0}
      onClick={() => input.current?.click()}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && input.current?.click()}
    >
      <input
        ref={input}
        type="file"
        accept="image/*"
        hidden
        onChange={(e) => {
          void handle(e.target.files?.[0])
          e.target.value = ''
        }}
      />
      {busy ? 'Looking at the picture…' : 'Drop a meme image here, or click to choose'}
      {message && <span className="text-stamp">{message}</span>}
    </div>
  )
}
