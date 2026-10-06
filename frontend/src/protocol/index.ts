// Protocol types are GENERATED from schemas/messages_v2.json into messages.d.ts (`npm run gen:types`).
// This module re-exports them and adds the one runtime helper the client needs: a structural check
// that an incoming frame is a known server message. Field-level validation is the backend's job.

import type { ServerToClient } from './messages'

export type * from './messages'

export type ServerMessageType = ServerToClient['type']

const SERVER_TYPES: ReadonlySet<string> = new Set<ServerMessageType>([
  'hello',
  'session_state',
  'input_review_result',
  'turn_accepted',
  'passage',
  'options',
  'phone_event',
  'room_state',
  'drama_state',
  'turn_trace',
  'error',
])

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** Structural check: an object with a known server `type`. */
export function isServerMessage(v: unknown): v is ServerToClient {
  return isRecord(v) && typeof v.type === 'string' && SERVER_TYPES.has(v.type)
}

export function parseServerMessage(raw: string): ServerToClient | null {
  try {
    const v: unknown = JSON.parse(raw)
    return isServerMessage(v) ? v : null
  } catch {
    return null
  }
}
