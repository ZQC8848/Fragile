import { useEffect, useState } from 'react'
import type { Control } from '../protocol'
import { api, type LlmRole } from '../net/api'
import { send } from '../net/ws'
import { useSessionStore } from '../store/session'
import { arr, at, num, str, type Json } from './util'

/** A = rule, B = llm, C = trained (backend-design.md §4.1). */
const SCORER = { A: 'rule', B: 'llm', C: 'trained' } as const

const control = (command: Control['command'], args?: Json) => send({ type: 'control', command, ...(args ? { args } : {}) })

/** Steering the drama manager (backend-design.md §7.4): scorer, temperature, forced beat, clock, state,
 * a turn injected with a hand-written M2 output, and which LLM roles run live. */
export function Controls({ drama }: { drama: Json | null }) {
  const lastError = useSessionStore((s) => s.lastError)
  const shelf = arr(at(drama, 'shelf'))
  const [beat, setBeat] = useState('')
  const [minutes, setMinutes] = useState('')
  const [patch, setPatch] = useState('{\n  "mia_composure": 0.2\n}')
  const [patchError, setPatchError] = useState<string | null>(null)
  const [tau, setTau] = useState(1)

  useEffect(() => {
    const t = num(at(drama, 'tau'))
    if (t !== null) setTau(t)
  }, [drama])

  return (
    <>
      <section className="panel-section">
        <h2>Drama manager</h2>
        <div className="control-row">
          <span>Scorer</span>
          {(['A', 'B', 'C'] as const).map((s) => (
            <button key={s} type="button" className={[s, SCORER[s]].includes(str(at(drama, 'scorer')) as (typeof SCORER)[keyof typeof SCORER]) ? 'is-active' : ''} title={SCORER[s]} onClick={() => control('set_scorer', { scorer: s })}>
              {s}
            </button>
          ))}
        </div>
        <div className="control-row">
          <label htmlFor="tau">Tau {tau.toFixed(2)}</label>
          <input
            id="tau"
            type="range"
            min={0.05}
            max={3}
            step={0.05}
            value={tau}
            onChange={(e) => setTau(Number(e.target.value))}
            onPointerUp={() => control('set_tau', { tau })}
            onKeyUp={() => control('set_tau', { tau })}
          />
        </div>
        <div className="control-row">
          <select value={beat} onChange={(e) => setBeat(e.target.value)} aria-label="Beat to force">
            <option value="">Force a beat next</option>
            {shelf.map((b) => (
              <option key={str(b.beat_id)} value={str(b.beat_id)}>
                {str(b.beat_id)}
                {b.eligible ? '' : ' (not eligible)'}
              </option>
            ))}
          </select>
          <button type="button" disabled={!beat} onClick={() => control('force_beat', { beat_id: beat })}>
            Force
          </button>
        </div>
        <div className="control-row">
          <input value={minutes} onChange={(e) => setMinutes(e.target.value)} placeholder="Story minute" aria-label="Jump the clock to" inputMode="decimal" />
          <button type="button" disabled={!minutes} onClick={() => control('jump_clock', { to_min: Number(minutes) })}>
            Jump clock
          </button>
        </div>
      </section>

      <section className="panel-section">
        <h2>State patch</h2>
        <textarea value={patch} onChange={(e) => setPatch(e.target.value)} rows={5} spellCheck={false} aria-label="State patch as JSON" />
        <div className="control-row">
          <button
            type="button"
            onClick={() => {
              try {
                control('set_state', { patch: JSON.parse(patch) as Json })
                setPatchError(null)
              } catch {
                setPatchError('The patch is not valid JSON.')
              }
            }}
          >
            Apply patch
          </button>
          <button type="button" className="is-danger" onClick={() => control('reset')}>
            Reset session
          </button>
        </div>
        {patchError && <p className="console-error">{patchError}</p>}
        {lastError && <p className="console-error">{lastError}</p>}
      </section>

      <LlmRoles />
    </>
  )
}

function LlmRoles() {
  const [roles, setRoles] = useState<LlmRole[]>([])
  const reload = () => api.llm().then(setRoles, () => setRoles([]))
  useEffect(() => {
    reload()
  }, [])
  return (
    <section className="panel-section">
      <h2>LLM roles</h2>
      <table>
        <tbody>
          {roles.map((r) => (
            <tr key={r.role}>
              <td>{r.role}</td>
              <td className="dim">{r.effective_provider === 'mock' ? 'mock' : r.model}</td>
              <td>
                <button
                  type="button"
                  disabled={!r.live && !r.can_go_live}
                  className={r.live ? 'is-active' : ''}
                  onClick={() => {
                    control('set_llm_live', { role: r.role, live: !r.live })
                    window.setTimeout(reload, 300)
                  }}
                >
                  {r.live ? 'Live' : 'Mock'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
