import { create } from 'zustand'
import type { Hello, ServerToClient } from '../protocol'

export type LayoutMode = 'play' | 'console'
export type ConnectionStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed'

interface SessionStore {
  sessionId: string | null
  connection: ConnectionStatus
  reconnectAttempt: number
  /** The server's greeting on the current connection. */
  hello: Hello | null
  lastError: string | null

  setConnection: (status: ConnectionStatus, attempt?: number) => void
  setError: (msg: string | null) => void
  /** Route any server message into the store. Called only by the WebSocket client. */
  ingest: (msg: ServerToClient) => void
}

export const useSessionStore = create<SessionStore>((set) => ({
  sessionId: null,
  connection: 'idle',
  reconnectAttempt: 0,
  hello: null,
  lastError: null,

  // a hello belongs to one connection: drop it as soon as that connection is gone
  setConnection: (status, attempt = 0) =>
    set((s) => ({ connection: status, reconnectAttempt: attempt, hello: status === 'open' ? s.hello : null })),
  setError: (msg) => set({ lastError: msg }),

  ingest: (msg) => {
    switch (msg.type) {
      case 'hello':
        set({ hello: msg, sessionId: msg.session, lastError: null })
        break
    }
  },
}))
