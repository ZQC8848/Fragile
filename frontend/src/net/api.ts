// REST client. Paths are fixed by the backend contract; all go through the Vite /api proxy in dev.
import type { Gender } from '../protocol'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${init?.method ?? 'GET'} ${path} -> ${res.status} ${text.slice(0, 200)}`)
  }
  return (await res.json()) as T
}

/** backend/data/cast.yaml, served by GET /api/intro (interaction-design.md §10.4). */
export interface CastCard {
  id: 'julian' | 'mia' | 'leo' | 'nora'
  name: string
  portrait: string
  relation: string
  memory: string
  footer?: string
}

export interface Intro {
  title: string
  premise: string[]
  cast: CastCard[]
  player: { relation: string; default_name: string; cards: { gender: Gender; portrait: string }[] }
}

/** backend/data/truth.yaml: only served once the session has ended. */
export interface Truth {
  title: string
  timeline: { when: string; what: string }[]
  shares: { who: string; what: string }[]
}

/** Art lives under the repository's art/ folder, served at /art. */
export const artUrl = (path: string) => `/art/${path}`

export interface SessionRow {
  id: string
  phase: 'lobby' | 'playing' | 'ended'
  turn: number
  ending: string | null
  watchers: number
}

export interface LlmRole {
  role: string
  live: boolean
  provider: string
  effective_provider: string
  model: string
  can_go_live: boolean
  temperature: number
}

export const api = {
  sessions: () => request<SessionRow[]>('/api/sessions'),
  turns: (sessionId: string) => request<Record<string, unknown>[]>(`/api/sessions/${encodeURIComponent(sessionId)}/turns`),
  state: (sessionId: string) => request<Record<string, unknown>>(`/api/sessions/${encodeURIComponent(sessionId)}/state`),
  llm: () => request<LlmRole[]>('/api/llm'),
  health: () => request<{ ok: boolean }>('/api/health'),
  intro: () => request<Intro>('/api/intro'),
  truth: (sessionId: string) => request<Truth>(`/api/sessions/${encodeURIComponent(sessionId)}/truth`),
}
