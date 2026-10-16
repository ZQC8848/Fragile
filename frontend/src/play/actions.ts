// Everything the play screen sends. The client never interprets the story: it reports what the player
// wrote or picked, and shows what the server sends back (interaction-design.md §10).
import type { Channels, Gender, InputSource } from '../protocol'
import { send, ws } from '../net/ws'
import { useSessionStore } from '../store/session'

const store = () => useSessionStore.getState()

function newSessionId(): string {
  return `p-${crypto.randomUUID().slice(0, 12)}`
}

/** Open a fresh session and walk through the door. */
export function startGame(name: string, gender: Gender): void {
  const id = newSessionId()
  store().beginPlay(id, name, gender)
  ws.connect(id, 'play')
  send({ type: 'session_start', name, gender })
}

/** The single box: ask the server to split, translate and check the line (no turn is used). */
export function reviewLine(text: string): void {
  store().setReviewing(true)
  store().setError(null)
  send({ type: 'input_review', mode: 'single', text })
}

/** Play a turn with these channels. Rejections come back as an input_review_result and use no turn. */
export function submitTurn(channels: Channels, source: InputSource, reviewId?: string): void {
  store().clearReview()
  store().setError(null)
  store().setPending({ player: channels, sentAt: Date.now() })
  send({ type: 'turn_submit', channels, source, ...(reviewId ? { review_id: reviewId } : {}) })
}

export function requestOptions(): void {
  store().setOptionsLoading(true)
  send({ type: 'options_request' })
}

export function openPhone(): void {
  store().markPhoneSeen()
  send({ type: 'phone_open' })
}

export function leaveGame(): void {
  ws.disconnect()
  store().resetPlay()
}

/** True when the edited channels are still exactly the reviewed draft. */
export function sameChannels(a: Channels, b: Channels): boolean {
  return (['speech', 'action', 'expression'] as const).every((k) => (a[k] ?? '') === (b[k] ?? '')) && (a.addressee ?? null) === (b.addressee ?? null)
}
