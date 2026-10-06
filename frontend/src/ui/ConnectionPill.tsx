import { ws } from '../net/ws'
import { useSessionStore } from '../store/session'

const LABEL: Record<string, string> = {
  idle: 'no session',
  connecting: 'connecting',
  open: 'live',
  reconnecting: 'reconnecting',
  closed: 'offline',
}

/** Small connection status indicator. Used on backstage surfaces; the Play route shows a quieter variant. */
export function ConnectionPill({ quiet = false }: { quiet?: boolean }) {
  const connection = useSessionStore((s) => s.connection)
  const attempt = useSessionStore((s) => s.reconnectAttempt)
  const sessionId = useSessionStore((s) => s.sessionId)
  const lastError = useSessionStore((s) => s.lastError)

  const danger = connection === 'closed' || connection === 'reconnecting'
  if (quiet && connection === 'open') return null

  return (
    <div
      className="backstage"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 8,
        padding: '3px 8px',
        border: `1px solid ${danger ? 'var(--accent)' : 'var(--line)'}`,
        borderRadius: 2,
        background: 'var(--bg-elev)',
        color: danger ? 'var(--accent)' : 'var(--ink-dim)',
        fontSize: 11,
      }}
      title={lastError ?? undefined}
    >
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: '50%',
          background: connection === 'open' ? 'var(--ink)' : danger ? 'var(--accent)' : 'var(--ink-dim)',
        }}
      />
      <span>
        {LABEL[connection] ?? connection}
        {connection === 'reconnecting' && attempt > 0 ? ` (${attempt})` : ''}
      </span>
      {sessionId && !quiet && <span style={{ color: 'var(--ink-dim)' }}>{sessionId.slice(0, 8)}</span>}
      {danger && (
        <button type="button" onClick={() => ws.retryNow()} style={{ padding: '0 6px', fontSize: 11 }}>
          retry
        </button>
      )}
    </div>
  )
}
