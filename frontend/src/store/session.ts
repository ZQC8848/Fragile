import { create } from 'zustand'
import type {
  Channels,
  Gender,
  Hello,
  InputReviewResult,
  Passage,
  PhoneEvent,
  PlayerCard,
  RoomState,
  ServerToClient,
} from '../protocol'

export type LayoutMode = 'play' | 'console'
export type ConnectionStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed'

/** The player's turn in flight: shown in the transcript at once, until its passage arrives. */
export interface PendingTurn {
  player: Channels
  sentAt: number
}

interface SessionStore {
  sessionId: string | null
  connection: ConnectionStatus
  reconnectAttempt: number
  /** The server's greeting on the current connection. */
  hello: Hello | null
  lastError: string | null

  // -- play (interaction-design.md §10) -----------------------------------------------
  phase: 'lobby' | 'playing' | 'ended'
  name: string
  gender: Gender
  card: PlayerCard | null
  passages: Passage[]
  pending: PendingTurn | null
  room: RoomState | null
  phone: PhoneEvent[]
  /** phone events the player has not looked at yet */
  phoneUnseen: number
  /** Nora's call is ringing: it arrived after the last passage and no turn has been played since */
  ringing: boolean
  reviewing: boolean
  review: InputReviewResult | null
  options: Channels[] | null
  optionsLoading: boolean

  // -- console (backend-design.md §7.4): the whole state and every turn record ---------------
  drama: Record<string, unknown> | null
  traces: Record<string, unknown>[]

  setConnection: (status: ConnectionStatus, attempt?: number) => void
  setError: (msg: string | null) => void
  beginPlay: (sessionId: string, name: string, gender: Gender) => void
  setPending: (pending: PendingTurn | null) => void
  setReviewing: (on: boolean) => void
  clearReview: () => void
  setOptionsLoading: (on: boolean) => void
  clearOptions: () => void
  markPhoneSeen: () => void
  resetPlay: () => void
  setTraces: (traces: Record<string, unknown>[]) => void
  setDrama: (drama: Record<string, unknown> | null) => void
  /** Route any server message into the store. Called only by the WebSocket client. */
  ingest: (msg: ServerToClient) => void
}

const freshPlay = {
  phase: 'lobby' as const,
  card: null,
  passages: [],
  pending: null,
  room: null,
  phone: [],
  phoneUnseen: 0,
  ringing: false,
  reviewing: false,
  review: null,
  options: null,
  optionsLoading: false,
}

export const useSessionStore = create<SessionStore>((set) => ({
  sessionId: null,
  connection: 'idle',
  reconnectAttempt: 0,
  hello: null,
  lastError: null,
  name: 'Sam',
  gender: 'female',
  ...freshPlay,
  drama: null,
  traces: [],

  // a hello belongs to one connection: drop it as soon as that connection is gone
  setConnection: (status, attempt = 0) =>
    set((s) => ({ connection: status, reconnectAttempt: attempt, hello: status === 'open' ? s.hello : null })),
  setError: (msg) => set({ lastError: msg }),
  beginPlay: (sessionId, name, gender) => set({ ...freshPlay, sessionId, name, gender, lastError: null }),
  setPending: (pending) => set({ pending }),
  setReviewing: (on) => set({ reviewing: on }),
  clearReview: () => set({ review: null }),
  setOptionsLoading: (on) => set({ optionsLoading: on }),
  clearOptions: () => set({ options: null }),
  markPhoneSeen: () => set({ phoneUnseen: 0 }),
  resetPlay: () => set({ ...freshPlay, sessionId: null }),
  setTraces: (traces) => set({ traces }),
  setDrama: (drama) => set({ drama }),

  ingest: (msg) => {
    switch (msg.type) {
      case 'hello':
        set({ hello: msg, sessionId: msg.session, lastError: null })
        break
      case 'session_state':
        set({ phase: msg.phase })
        break
      case 'player_card':
        set({ card: msg })
        break
      case 'input_review_result':
        // a rejected submit also arrives this way: the turn did not happen
        set({ review: msg, reviewing: false, pending: msg.verdict === 'rejected' ? null : useSessionStore.getState().pending })
        break
      case 'passage':
        set((s) => ({ passages: [...s.passages, msg], pending: null, ringing: false, review: null, options: null }))
        break
      case 'options':
        set({ options: [...msg.items], optionsLoading: false })
        break
      case 'phone_event':
        set((s) => {
          if (msg.id && s.phone.some((e) => e.id === msg.id && e.kind === msg.kind)) return {}
          return {
            phone: [...s.phone, msg],
            phoneUnseen: s.phoneUnseen + 1,
            ringing: msg.kind === 'call_incoming' ? true : msg.from === 'nora' ? false : s.ringing,
          }
        })
        break
      case 'room_state':
        set({ room: msg })
        break
      case 'drama_state':
        set({ drama: msg })
        break
      case 'turn_trace':
        set((s) => ({ traces: [...s.traces.filter((t) => t.turn !== msg.turn), msg.record] }))
        break
      case 'error':
        set({ lastError: msg.message, reviewing: false, optionsLoading: false })
        break
    }
  },
}))
