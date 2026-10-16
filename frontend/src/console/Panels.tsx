import { useSessionStore } from '../store/session'
import { arr, at, num, str, type Json } from './util'

/** The values the drama turns on, then the state as the scorers read it. */
export function StatePanel({ drama }: { drama: Json | null }) {
  const s = (at(drama, 'state') as Json) ?? {}
  const rows: [string, unknown][] = [
    ['phase', s.story_phase],
    ['story minute', s.story_min],
    ['tension', s.tension],
    ['side', s.side],
    ['julian composure', s.julian_composure],
    ['mia composure', s.mia_composure],
    ['couple unity', s.couple_unity],
    ['nora told', s.nora_told],
    ['threatened julian', s.threatened_julian],
    ['police', s.police_called ? 'called' : `${str(s.police_blocks, '0')} blocked`],
    ['rooms', `you ${str(s.player_room)} · J ${str(s.julian_room)} · M ${str(s.mia_room)} · N ${str(s.nora_room)}`],
    ['revealed', arr<string>(s.revealed).join(', ')],
    ['current beat', `${str(s.current_beat, '—')} step ${str(s.beat_step)}`],
    ['ending', s.ending],
  ]
  return (
    <section className="panel-section">
      <h2>State</h2>
      <table>
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td className="dim">{k}</td>
              <td>{typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(2)) : str(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <details>
        <summary>State as the scorers read it</summary>
        <pre className="json">{str(at(drama, 'state_text'))}</pre>
      </details>
    </section>
  )
}

/** Every beat decision this session, newest first. */
export function DecisionLog() {
  const traces = useSessionStore((s) => s.traces)
  const decisions = traces
    .map((t) => ({ turn: num(t.turn) ?? 0, d: at(t, 'decision') as Json | null }))
    .filter((x): x is { turn: number; d: Json } => Boolean(x.d))
    .sort((a, b) => b.turn - a.turn)
  return (
    <section className="panel-section">
      <h2>Decisions</h2>
      {decisions.length === 0 && <p className="dim">No decisions yet.</p>}
      <table>
        <tbody>
          {decisions.map(({ turn, d }) => (
            <tr key={`${turn}-${str(d.decision_idx)}`} title={str(d.reasoning)}>
              <td className="dim">t{turn}</td>
              <td>{str(d.chosen, '(none)')}</td>
              <td className="dim">{str(d.kind)}</td>
              <td className="dim">{str(d.scorer)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

/** Every beat and its standing right now: eligible ones first, then why the others are not. */
export function Shelf({ drama }: { drama: Json | null }) {
  const shelf = arr(at(drama, 'shelf'))
  return (
    <section className="panel-section">
      <h2>Beat shelf</h2>
      <table>
        <tbody>
          {shelf.map((b) => (
            <tr key={str(b.beat_id)} className={b.current ? 'is-chosen' : b.eligible ? '' : 'is-dim'}>
              <td>{str(b.beat_id)}</td>
              <td className="dim">{str(b.type)}</td>
              <td className="dim">{b.played ? 'played' : b.eligible ? `p ${str(b.priority)}` : str(b.reason)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
