// Hand-written M0 protocol. The real message set (interaction-design.md section 11) is defined in
// schemas/messages_v2.json in M1; `npm run gen:types` then writes messages.d.ts next to this file and
// these hand-written shapes give way to the generated ones.

/** Server -> client: sent once, right after the WebSocket is accepted. */
export interface Hello {
  type: 'hello'
  session: string
}

export type ServerToClient = Hello

/** Client -> server. M0 backends ignore everything the client sends. */
export interface ClientMessage {
  type: string
  [key: string]: unknown
}

export type ClientToServer = ClientMessage

export type ServerMessageType = ServerToClient['type']

const SERVER_TYPES: ReadonlySet<string> = new Set<ServerMessageType>(['hello'])

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** Structural check: an object with a known server `type`. Field-level validation is the backend's job. */
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
