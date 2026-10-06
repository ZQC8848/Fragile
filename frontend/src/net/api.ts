// REST client. Paths are fixed by the backend contract; all go through the Vite /api proxy in dev.
// M0 backends only serve /api/health; the session, beat, decision and annotation endpoints return in M3.

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

export const api = {
  health: () => request<{ ok: boolean }>('/api/health'),
}
