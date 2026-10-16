// Turn records and the drama state are plain JSON from the backend: these read them without a schema.

export type Json = Record<string, unknown>

export function at(obj: unknown, path: string): unknown {
  let cur: unknown = obj
  for (const part of path.split('.')) {
    if (cur && typeof cur === 'object' && part in (cur as Json)) cur = (cur as Json)[part]
    else return undefined
  }
  return cur
}

export const str = (v: unknown, fallback = ''): string => (v === null || v === undefined ? fallback : typeof v === 'string' ? v : JSON.stringify(v))
export const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
export const arr = <T = Json>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : [])

export function secs(ms: unknown): string {
  const n = num(ms)
  return n === null ? '' : n >= 1000 ? `${(n / 1000).toFixed(1)} s` : `${Math.round(n)} ms`
}
