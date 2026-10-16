import { useState } from 'react'
import { useSessionStore } from '../store/session'
import { arr, at, num, secs, str, type Json } from './util'

/** One row per turn; open a row to follow the whole chain (interaction-design.md §10.7): input, review,
 * M2 units, world, reactions, the beat and its steps, clock, decision, narrator, guard, state, latency. */
export function TurnInspector() {
  const traces = useSessionStore((s) => s.traces)
  const [open, setOpen] = useState<number | null>(null)
  const sorted = [...traces].sort((a, b) => (num(b.turn) ?? 0) - (num(a.turn) ?? 0))

  return (
    <section className="panel-section">
      <h2>Turns</h2>
      {sorted.length === 0 && <p className="dim">No turns yet.</p>}
      <ol className="turns">
        {sorted.map((t) => {
          const n = num(t.turn) ?? 0
          const isOpen = open === n
          return (
            <li key={n} className={isOpen ? 'is-open' : ''}>
              <button type="button" className="turn-row" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : n)}>
                <span className="turn-no">{n}</span>
                <span className="turn-input">{inputSummary(t)}</span>
                <span className="dim">{str(at(t, 'beat.run.beat_id')) || str(at(t, 'decision.chosen'))}</span>
                <span className="dim">{guardSummary(t)}</span>
                <span className="dim turn-time">{secs(at(t, 'latency_ms.total'))}</span>
              </button>
              {isOpen && <TurnDetail t={t} />}
            </li>
          )
        })}
      </ol>
    </section>
  )
}

function inputSummary(t: Json): string {
  if (num(t.turn) === 0) return 'opening'
  const ch = at(t, 'input.channels') as Json | undefined
  const parts = [ch?.action, ch?.expression, ch?.speech ? `"${str(ch.speech)}"` : ''].filter(Boolean).map((v) => str(v))
  return parts.join(' ') || '(silence)'
}

function guardSummary(t: Json): string {
  const rounds = arr(t.guard)
  const rewrites = Math.max(0, rounds.length - 1)
  const fallback = Boolean(at(t, 'narrator.fallback'))
  const repaired = Boolean(at(t, 'narrator.repaired'))
  return [rewrites ? `${rewrites} rewrite${rewrites > 1 ? 's' : ''}` : '', repaired ? 'repaired' : '', fallback ? 'fallback text' : ''].filter(Boolean).join(', ')
}

function TurnDetail({ t }: { t: Json }) {
  const review = at(t, 'input.review') as Json | null
  const units = arr(at(t, 'understanding.units'))
  const reactions = at(t, 'reactions') as Json
  const decision = at(t, 'decision') as Json | null
  const segments = arr(at(t, 'narrator.segments'))
  return (
    <div className="turn-detail">
      <Block title="Input and review">
        <KV k="source" v={at(t, 'input.source')} />
        <KV k="validity" v={at(review, 'validity.label') ?? at(t, 'understanding.validity.label')} />
        <KV k="translated" v={at(t, 'understanding.translated')} />
        <KV k="suspicion" v={at(t, 'understanding.suspicion')} />
        <KV k="claims" v={at(t, 'understanding.claims')} />
      </Block>
      <Block title="M2 units">
        <table>
          <tbody>
            {units.map((u, i) => (
              <tr key={i}>
                <td className="dim">{str(u.channel)}</td>
                <td>{str(u.act)}</td>
                <td className="dim">{str(u.addressee)}</td>
                <td>{str(u.text)}</td>
                <td className="dim">{u.action ? str(u.action) : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Block>
      <Block title="World">
        <KV k="status" v={at(t, 'world.status')} />
        <KV k="action" v={at(t, 'world.action')} />
        <KV k="note" v={at(t, 'world.note')} />
        <KV k="before" v={at(t, 'world.before')} />
        <KV k="moved" v={at(t, 'world.moved')} />
      </Block>
      <Block title="Reactions">
        <KV k="primary" v={at(reactions, 'primary.id')} />
        <KV k="secondary" v={at(reactions, 'secondary.id')} />
        <KV k="rules" v={arr(at(reactions, 'rules')).map((r) => str(r.id ?? r))} />
        <KV k="candidates" v={arr(at(reactions, 'candidates')).map((c) => `${str(c.id)} (${str(c.priority)})`)} />
        <KV k="clipped" v={at(reactions, 'clipped')} />
      </Block>
      <Block title="Beat and clock">
        <KV k="run" v={at(t, 'beat.run')} />
        <KV k="planned" v={at(t, 'beat.planned')} />
        <KV k="outcome" v={at(t, 'beat.outcome')} />
        <KV k="ended" v={at(t, 'beat.ended')} />
        <KV k="clock" v={at(t, 'clock')} />
      </Block>
      {decision && (
        <Block title="Decision">
          <KV k="kind" v={decision.kind} />
          <KV k="chosen" v={`${str(decision.chosen)} (${str(decision.entry)})`} />
          <KV k="reasoning" v={decision.reasoning} />
          <Candidates rows={arr(decision.candidates)} />
        </Block>
      )}
      <Block title="Narrator">
        <KV k="model" v={at(t, 'narrator.meta.model')} />
        <KV k="errors" v={at(t, 'narrator.meta.errors')} />
        <ol className="segments">
          {segments.map((s, i) => (
            <li key={i}>
              <span className="dim">{str(s.kind)}{s.speaker ? `:${str(s.speaker)}` : ''}</span> {str(s.text)}
            </li>
          ))}
        </ol>
      </Block>
      <Block title="Guard">
        {arr(t.guard).map((round, i) => (
          <div key={i}>
            <KV k={`round ${i}`} v={arr(at(round, 'verdicts.result.verdicts')).filter((v) => v.label !== 'consistent').map((v) => `${str(v.index)} ${str(v.label)} ${str(v.span)}`)} />
          </div>
        ))}
      </Block>
      <Block title="State changes">
        <table>
          <tbody>
            {Object.entries((at(t, 'state_diff') as Json) ?? {})
              .filter(([k]) => !['heard_by', 'claims', 'beat_history'].includes(k))
              .map(([k, v]) => (
                <tr key={k}>
                  <td>{k}</td>
                  <td className="dim">{str(at(v, 'from'))}</td>
                  <td>{str(at(v, 'to'))}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </Block>
      <Block title="Latency and LLM calls">
        <KV k="stages" v={Object.entries((at(t, 'latency_ms') as Json) ?? {}).map(([k, v]) => `${k} ${secs(v)}`)} />
        <table>
          <tbody>
            {arr(t.llm_calls).map((c, i) => (
              <tr key={i}>
                <td>{str(c.role)}</td>
                <td className="dim">{str(c.model)}</td>
                <td>{secs(c.latency_ms)}</td>
                <td className="dim">{arr(c.errors).length ? arr<string>(c.errors).join('; ') : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Block>
    </div>
  )
}

function Candidates({ rows }: { rows: Json[] }) {
  if (!rows.length) return null
  return (
    <table>
      <thead>
        <tr>
          <th>beat</th>
          <th>p</th>
          <th>scores</th>
          <th>why</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((c) => (
          <tr key={str(c.beat_id)} className={c.chosen ? 'is-chosen' : ''}>
            <td>{str(c.beat_id)}</td>
            <td>{num(c.probability)?.toFixed(2) ?? ''}</td>
            <td className="dim">{str(c.scores)}</td>
            <td className="dim">{Object.values((c.reasons as Json) ?? {}).map((r) => str(r)).join(' ')}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="block">
      <h3>{title}</h3>
      {children}
    </div>
  )
}

function KV({ k, v }: { k: string; v: unknown }) {
  if (v === undefined || v === null || (Array.isArray(v) && v.length === 0)) return null
  return (
    <div className="kv">
      <span className="dim">{k}</span> <span>{Array.isArray(v) ? v.map((x) => str(x)).join(', ') : str(v)}</span>
    </div>
  )
}
