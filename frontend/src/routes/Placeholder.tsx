import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { api } from '../net/api'
import { ws } from '../net/ws'
import { useSessionStore, type LayoutMode } from '../store/session'
import { ConnectionPill } from '../ui/ConnectionPill'

/** Every M0 page talks to the same dev session; session creation arrives with app/session.py in M3. */
const DEV_SESSION = 'dev'

/** M0 placeholder page: opens the WebSocket and shows what the backend said. Replaced in M5. */
export function Placeholder({ mode, title }: { mode: LayoutMode; title: string }) {
  const hello = useSessionStore((s) => s.hello)
  const lastError = useSessionStore((s) => s.lastError)
  const [health, setHealth] = useState('checking')

  useEffect(() => {
    ws.connect(DEV_SESSION, mode)
  }, [mode])

  useEffect(() => {
    let cancelled = false
    api.health().then(
      (r) => {
        if (!cancelled) setHealth(r.ok ? 'ok' : 'not ok')
      },
      (err: unknown) => {
        if (!cancelled) setHealth(`unreachable: ${err instanceof Error ? err.message : String(err)}`)
      },
    )
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="backstage" style={{ height: '100%', overflow: 'auto', padding: 16, boxSizing: 'border-box' }}>
      <div style={{ maxWidth: 640, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 16 }}>
        <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ fontFamily: 'var(--sans)', fontSize: 18, letterSpacing: '0.04em' }}>Fragile · {title}</div>
          <ConnectionPill />
        </header>
        <nav style={{ display: 'flex', gap: 12 }}>
          <NavLink to="/play" style={({ isActive }) => ({ color: isActive ? 'var(--ink)' : 'var(--ink-dim)' })}>
            play
          </NavLink>
          <NavLink to="/console" style={({ isActive }) => ({ color: isActive ? 'var(--ink)' : 'var(--ink-dim)' })}>
            console
          </NavLink>
        </nav>
        <section className="panel-section" style={{ border: '1px solid var(--line)' }}>
          <h2>websocket /ws/{DEV_SESSION}</h2>
          <pre className="json">{hello ? JSON.stringify(hello) : 'waiting for hello'}</pre>
          {lastError && <div style={{ color: 'var(--accent)', marginTop: 6 }}>{lastError}</div>}
        </section>
        <section className="panel-section" style={{ border: '1px solid var(--line)' }}>
          <h2>backend /api/health</h2>
          <div style={{ color: health === 'ok' ? 'var(--ink)' : 'var(--ink-dim)' }}>{health}</div>
        </section>
        <p style={{ color: 'var(--ink-dim)', margin: 0 }}>
          Placeholder. The {title.toLowerCase()} view is built in M5.
        </p>
      </div>
    </div>
  )
}
