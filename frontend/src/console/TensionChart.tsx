import { useMemo, useRef, useState } from 'react'
import { useSessionStore } from '../store/session'
import { arr, at, num, type Json } from './util'

// Three series, validated with the dataviz palette checker on the Console surface #1b222c (Night, dark):
// target arc = slot 1 blue (dashed), declared by beats = slot 2 orange (solid), measured by M4 = slot 3 aqua (dots).
const SERIES = {
  target: { label: 'Target arc', color: '#3987e5' },
  declared: { label: 'Declared by beats', color: '#d95926' },
  measured: { label: 'Measured (M4)', color: '#199e70' },
} as const

const W = 340
const H = 190
const PAD = { l: 28, r: 12, t: 10, b: 24 }
const T_MAX = 5

type Pt = [number, number]

/** Tension over story minutes (plan.md M5): the arc the DM aims for, what the beats declared, what M4 read. */
export function TensionChart({ drama }: { drama: Json | null }) {
  const traces = useSessionStore((s) => s.traces)
  const [hover, setHover] = useState<number | null>(null)
  const [asTable, setAsTable] = useState(false)
  const svg = useRef<SVGSVGElement>(null)

  const data = useMemo(() => {
    const target = arr<Pt>(at(drama, 'arc')).map(([m, t]) => [Number(m), Number(t)] as Pt)
    const declared = [...traces]
      .sort((a, b) => (num(a.turn) ?? 0) - (num(b.turn) ?? 0))
      .map((t) => [num(at(t, 'state.story_min')), num(at(t, 'state.tension'))])
      .filter((p): p is Pt => p[0] !== null && p[1] !== null)
    const measured = arr(at(drama, 'tension_trace'))
      .map((p) => [num(p.story_min), num(p.tension)])
      .filter((p): p is Pt => p[0] !== null && p[1] !== null)
    const xMax = Math.max(1, ...target.map((p) => p[0]), ...declared.map((p) => p[0]), ...measured.map((p) => p[0]))
    return { target, declared, measured, xMax }
  }, [drama, traces])

  const x = (m: number) => PAD.l + (m / data.xMax) * (W - PAD.l - PAD.r)
  const y = (t: number) => H - PAD.b - (t / T_MAX) * (H - PAD.t - PAD.b)
  const line = (pts: Pt[]) => pts.map((p, i) => `${i ? 'L' : 'M'}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join('')

  // the crosshair snaps to the nearest story minute that has a declared value
  const valueAt = (pts: Pt[], m: number): number | null => {
    let best: Pt | null = null
    for (const p of pts) if (!best || Math.abs(p[0] - m) < Math.abs(best[0] - m)) best = p
    return best && Math.abs(best[0] - m) <= data.xMax * 0.04 ? best[1] : null
  }
  const arcAt = (m: number): number | null => {
    const pts = data.target
    const first = pts[0]
    const last = pts[pts.length - 1]
    if (!first || !last) return null
    if (m <= first[0]) return first[1]
    for (let i = 1; i < pts.length; i++) {
      const [x0, y0] = pts[i - 1] as Pt
      const [x1, y1] = pts[i] as Pt
      if (m <= x1) return y0 + ((y1 - y0) * (m - x0)) / (x1 - x0)
    }
    return last[1]
  }

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const box = svg.current?.getBoundingClientRect()
    if (!box) return
    const px = ((e.clientX - box.left) / box.width) * W
    const m = ((px - PAD.l) / (W - PAD.l - PAD.r)) * data.xMax
    const snaps = [...data.declared, ...data.measured].map((p) => p[0])
    if (!snaps.length) return setHover(null)
    setHover(snaps.reduce((a, b) => (Math.abs(b - m) < Math.abs(a - m) ? b : a)))
  }

  const tip = hover === null ? null : { m: hover, target: arcAt(hover), declared: valueAt(data.declared, hover), measured: valueAt(data.measured, hover) }

  return (
    <section className="panel-section">
      <div className="chart-head">
        <h2>Tension</h2>
        <button type="button" onClick={() => setAsTable(!asTable)}>
          {asTable ? 'Chart' : 'Table'}
        </button>
      </div>
      <ul className="legend">
        {Object.entries(SERIES).map(([k, s]) => (
          <li key={k}>
            <svg width="18" height="8" aria-hidden="true">
              {k === 'measured' ? (
                <circle cx="9" cy="4" r="3.5" fill={s.color} />
              ) : (
                <line x1="1" y1="4" x2="17" y2="4" stroke={s.color} strokeWidth="2" strokeDasharray={k === 'target' ? '4 3' : undefined} />
              )}
            </svg>
            {s.label}
          </li>
        ))}
      </ul>
      {asTable ? (
        <table>
          <thead>
            <tr>
              <th>Story minute</th>
              <th>Target</th>
              <th>Declared</th>
              <th>Measured</th>
            </tr>
          </thead>
          <tbody>
            {[...new Set([...data.declared, ...data.measured].map((p) => p[0]))]
              .sort((a, b) => a - b)
              .map((m) => (
                <tr key={m}>
                  <td>{m.toFixed(1)}</td>
                  <td>{arcAt(m)?.toFixed(2) ?? ''}</td>
                  <td>{valueAt(data.declared, m)?.toFixed(2) ?? ''}</td>
                  <td>{valueAt(data.measured, m)?.toFixed(2) ?? ''}</td>
                </tr>
              ))}
          </tbody>
        </table>
      ) : (
        <div className="chart">
          <svg
            ref={svg}
            viewBox={`0 0 ${W} ${H}`}
            role="img"
            aria-label="Tension over story minutes: target arc, declared by beats, measured by M4"
            onPointerMove={onMove}
            onPointerLeave={() => setHover(null)}
          >
            {[0, 1, 2, 3, 4, 5].map((t) => (
              <g key={t}>
                <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} className="grid" />
                <text x={PAD.l - 6} y={y(t) + 3} className="tick" textAnchor="end">
                  {t}
                </text>
              </g>
            ))}
            {[0, 6, 12, 18].filter((m) => m <= data.xMax).map((m) => (
              <text key={m} x={x(m)} y={H - 8} className="tick" textAnchor="middle">
                {m} min
              </text>
            ))}
            <path d={line(data.target)} fill="none" stroke={SERIES.target.color} strokeWidth="2" strokeDasharray="5 4" />
            <path d={line(data.declared)} fill="none" stroke={SERIES.declared.color} strokeWidth="2" />
            {data.measured.map((p, i) => (
              <circle key={i} cx={x(p[0])} cy={y(p[1])} r="4" fill={SERIES.measured.color} stroke="var(--bg)" strokeWidth="2" />
            ))}
            {tip && <line x1={x(tip.m)} x2={x(tip.m)} y1={PAD.t} y2={H - PAD.b} className="crosshair" />}
          </svg>
          {tip && (
            <div className="tooltip" style={{ left: `${(x(tip.m) / W) * 100}%` }}>
              <div className="dim">{tip.m.toFixed(1)} min</div>
              {(['target', 'declared', 'measured'] as const).map((k) =>
                tip[k] === null ? null : (
                  <div key={k} className="tip-row">
                    <svg width="12" height="6" aria-hidden="true">
                      <line x1="0" y1="3" x2="12" y2="3" stroke={SERIES[k].color} strokeWidth="2" />
                    </svg>
                    <strong>{(tip[k] as number).toFixed(2)}</strong> <span className="dim">{SERIES[k].label}</span>
                  </div>
                ),
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}
