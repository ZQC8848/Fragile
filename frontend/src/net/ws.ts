// The single data entry point. Connects to ws://<host>/ws/<session>?mode=<mode>,
// reconnects with backoff, and routes every incoming message into the Zustand store by `type`.
import { parseServerMessage, type ClientToServer } from '../protocol'
import { useSessionStore, type LayoutMode } from '../store/session'

const BACKOFF_MS = [500, 1000, 2000, 4000, 8000, 15000]
// Player-originated messages (interaction-design.md section 11) are queued while offline and flushed on
// reconnect; telemetry and console controls are dropped.
const QUEUED_TYPES: ReadonlySet<string> = new Set(['session_start', 'input_review', 'turn_submit'])

class WsClient {
  private socket: WebSocket | null = null
  private session: string | null = null
  private mode: LayoutMode = 'play'
  private attempt = 0
  private retryTimer: number | null = null
  private closedByUser = false
  private queue: string[] = []

  connect(session: string, mode: LayoutMode): void {
    if (this.socket && this.session === session && this.mode === mode && !this.closedByUser) return
    this.disconnect()
    this.session = session
    this.mode = mode
    this.closedByUser = false
    this.attempt = 0
    this.open()
  }

  disconnect(): void {
    this.closedByUser = true
    if (this.retryTimer !== null) {
      window.clearTimeout(this.retryTimer)
      this.retryTimer = null
    }
    if (this.socket) {
      const s = this.socket
      this.socket = null
      s.onclose = null
      s.onerror = null
      s.onmessage = null
      s.onopen = null
      if (s.readyState === WebSocket.OPEN || s.readyState === WebSocket.CONNECTING) s.close()
    }
    useSessionStore.getState().setConnection('closed')
  }

  /** Force an immediate reconnect attempt (used by the connection pill's retry button). */
  retryNow(): void {
    if (!this.session) return
    if (this.retryTimer !== null) {
      window.clearTimeout(this.retryTimer)
      this.retryTimer = null
    }
    if (this.socket) return
    this.closedByUser = false
    this.open()
  }

  send(msg: ClientToServer): boolean {
    const raw = JSON.stringify(msg)
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(raw)
      return true
    }
    if (QUEUED_TYPES.has(msg.type)) {
      this.queue.push(raw)
      if (this.queue.length > 20) this.queue.shift()
    }
    return false
  }

  private url(): string {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${location.host}/ws/${encodeURIComponent(this.session ?? '')}?mode=${this.mode}`
  }

  private open(): void {
    if (!this.session) return
    const store = useSessionStore.getState()
    store.setConnection(this.attempt === 0 ? 'connecting' : 'reconnecting', this.attempt)
    let socket: WebSocket
    try {
      socket = new WebSocket(this.url())
    } catch (err) {
      store.setError(`websocket failed to construct: ${String(err)}`)
      this.scheduleRetry()
      return
    }
    this.socket = socket

    socket.onopen = () => {
      if (this.socket !== socket) return
      this.attempt = 0
      useSessionStore.getState().setConnection('open', 0)
      for (const raw of this.queue.splice(0)) socket.send(raw)
    }

    socket.onmessage = (ev) => {
      if (this.socket !== socket) return
      const data = typeof ev.data === 'string' ? ev.data : ''
      const msg = parseServerMessage(data)
      if (!msg) {
        console.warn('unrecognized server message', data.slice(0, 200))
        return
      }
      useSessionStore.getState().ingest(msg)
    }

    socket.onerror = () => {
      // onclose always follows; nothing to do here.
    }

    socket.onclose = () => {
      if (this.socket !== socket) return
      this.socket = null
      if (this.closedByUser) return
      this.scheduleRetry()
    }
  }

  private scheduleRetry(): void {
    if (this.closedByUser || this.retryTimer !== null) return
    const delay = BACKOFF_MS[Math.min(this.attempt, BACKOFF_MS.length - 1)] ?? 15000
    this.attempt += 1
    useSessionStore.getState().setConnection('reconnecting', this.attempt)
    this.retryTimer = window.setTimeout(() => {
      this.retryTimer = null
      this.open()
    }, delay)
  }
}

export const ws = new WsClient()

export function send(msg: ClientToServer): boolean {
  return ws.send(msg)
}
