import { useEffect, useRef, useState } from 'react'
import type { Channels, Npc, Passage, Segment } from '../protocol'
import { artUrl } from '../net/api'
import { useSessionStore } from '../store/session'
import { PERSON_NAME } from './ui'

/** The reading column: every passage in order, illustrations inline, the newest one revealed line by line. */
export function Transcript({ onPerson }: { onPerson: (who: Npc) => void }) {
  const passages = useSessionStore((s) => s.passages)
  const pending = useSessionStore((s) => s.pending)
  const end = useRef<HTMLDivElement>(null)

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [passages.length, pending])

  return (
    <div className="column transcript" aria-live="polite">
      {passages.map((p, i) => (
        <PassageView key={`${p.turn}-${i}`} passage={p} reveal={i === passages.length - 1} onPerson={onPerson} />
      ))}
      {pending && (
        <section className="passage">
          <PlayerLine channels={pending.player} />
          <Waiting since={pending.sentAt} />
        </section>
      )}
      <div ref={end} />
    </div>
  )
}

function PassageView({ passage, reveal, onPerson }: { passage: Passage; reveal: boolean; onPerson: (who: Npc) => void }) {
  const segments = passage.segments
  const [shown, setShown] = useState(reveal ? 0 : segments.length)

  useEffect(() => {
    if (shown >= segments.length) return
    const t = window.setTimeout(() => setShown((n) => n + 1), shown === 0 ? 150 : 650)
    return () => window.clearTimeout(t)
  }, [shown, segments.length])

  const ill = passage.illustration
  return (
    <section className="passage" onClick={() => setShown(segments.length)}>
      {passage.player && <PlayerLine channels={passage.player} />}
      {ill && (
        <figure className="illustration">
          {ill.src ? <img src={artUrl(ill.src)} alt={ill.caption} /> : <figcaption className="caption-card">{ill.caption}</figcaption>}
        </figure>
      )}
      {segments.map((s, i) => (
        <SegmentView key={i} segment={s} visible={i < shown} onPerson={onPerson} />
      ))}
    </section>
  )
}

function SegmentView({ segment, visible, onPerson }: { segment: Segment; visible: boolean; onPerson: (who: Npc) => void }) {
  const cls = `seg seg-${segment.kind}${visible ? ' is-visible' : ''}`
  if (segment.kind === 'speech' && segment.speaker) {
    const who = segment.speaker
    return (
      <p className={cls}>
        <button type="button" className="speaker" onClick={(e) => (e.stopPropagation(), onPerson(who))}>
          {PERSON_NAME[who]}
        </button>{' '}
        {segment.text}
      </p>
    )
  }
  if (segment.kind === 'me_speech') return <p className={cls}>“{segment.text}”</p>
  return <p className={cls}>{segment.text}</p>
}

const CHANNEL_LABEL: [keyof Channels, string][] = [
  ['speech', 'Say'],
  ['action', 'Do'],
  ['expression', 'Face'],
]

/** What the player wrote this turn, small and grey, above the passage it produced. */
export function PlayerLine({ channels }: { channels: Channels }) {
  const parts = CHANNEL_LABEL.filter(([k]) => channels[k])
  const to = channels.addressee && channels.addressee !== 'self' ? channels.addressee : null
  return (
    <dl className="player-line">
      {parts.length === 0 && (
        <div>
          <dt>Silent</dt>
        </div>
      )}
      {parts.map(([k, label]) => (
        <div key={k}>
          <dt>{label}</dt>
          <dd>{channels[k] as string}</dd>
        </div>
      ))}
      {to && (
        <div>
          <dt>To</dt>
          <dd>{to === 'both' ? 'Julian and Mia' : PERSON_NAME[to]}</dd>
        </div>
      )}
    </dl>
  )
}

/** A quiet "…" while the turn is written; a plain note if nothing has come back for three minutes. */
function Waiting({ since }: { since: number }) {
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    const t = window.setTimeout(() => setSlow(true), Math.max(0, since + 180_000 - Date.now()))
    return () => window.clearTimeout(t)
  }, [since])
  return (
    <p className="waiting" role="status" aria-label="Writing the next passage">
      <span className="ellipsis">…</span>
      {slow && <span className="muted"> Still writing. This turn is taking longer than usual.</span>}
    </p>
  )
}
