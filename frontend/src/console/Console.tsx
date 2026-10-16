import { useCallback, useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { api, type SessionRow } from '../net/api'
import { send, ws } from '../net/ws'
import { useSessionStore } from '../store/session'
import { ConnectionPill } from '../ui/ConnectionPill'
import { Controls } from './Controls'
import { DecisionLog, Shelf, StatePanel } from './Panels'
import { TensionChart } from './TensionChart'
import { TurnInspector } from './TurnInspector'

/** The Console (backend-design.md §7.4, interaction-design.md §10.7): watch any session in this backend,
 * read every turn's full record, and steer the drama manager. It sees everything, secrets included. */
export function Console() {
  const [rows, setRows] = useState<SessionRow[]>([])
  const [watching, setWatching] = useState<string | null>(null)
  const drama = useSessionStore((s) => s.drama)

  const refresh = useCallback(() => {
    api.sessions().then(setRows, () => setRows([]))
  }, [])

  useEffect(() => {
    refresh()
    const t = window.setInterval(refresh, 5000)
    return () => window.clearInterval(t)
  }, [refresh])

  const watch = useCallback((id: string) => {
    setWatching(id)
    const store = useSessionStore.getState()
    store.setTraces([])
    store.setDrama(null)
    ws.connect(id, 'console')
    api.turns(id).then(store.setTraces, () => undefined)
    api.state(id).then(store.setDrama, () => undefined)
  }, [])

  const startTest = () => {
    const id = `c-${crypto.randomUUID().slice(0, 8)}`
    watch(id)
    // controls are not queued while offline: wait for this socket to open, then start
    const unsubscribe = useSessionStore.subscribe((st) => {
      if (st.connection !== 'open') return
      unsubscribe()
      send({ type: 'control', command: 'start', args: { name: 'Sam', gender: 'female' } })
      window.setTimeout(refresh, 800)
    })
  }

  return (
    <div className="backstage console">
      <header className="console-head">
        <strong>Fragile console</strong>
        <label>
          Session{' '}
          <select value={watching ?? ''} onChange={(e) => e.target.value && watch(e.target.value)}>
            <option value="">Choose a session</option>
            {rows.map((r) => (
              <option key={r.id} value={r.id}>
                {r.id} · {r.phase} · turn {r.turn}
                {r.ending ? ` · ${r.ending}` : ''}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={startTest}>
          New test session
        </button>
        <ConnectionPill />
        <NavLink to="/play" className="console-link">
          Play screen
        </NavLink>
      </header>
      {!watching ? (
        <p className="console-empty">Choose a session to watch, or start a test session. Sessions started from the play screen appear here.</p>
      ) : (
        <div className="console-grid">
          <aside className="console-col">
            <Controls drama={drama} />
          </aside>
          <main className="console-col console-main">
            <TurnInspector />
          </main>
          <aside className="console-col">
            <StatePanel drama={drama} />
            <TensionChart drama={drama} />
            <DecisionLog />
            <Shelf drama={drama} />
          </aside>
        </div>
      )}
    </div>
  )
}
