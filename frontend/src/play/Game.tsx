import { useCallback, useRef, useState } from 'react'
import type { Npc, PhoneEvent } from '../protocol'
import { api, artUrl, type CastCard, type Intro, type Truth } from '../net/api'
import { useSessionStore } from '../store/session'
import { leaveGame, openPhone } from './actions'
import { Composer } from './Composer'
import { useDraft } from './draft'
import { CastCardView } from './IntroFlow'
import { Transcript } from './Transcript'
import { MAP_ROOMS, PERSON_NAME, ROOM_NAME, useDismiss } from './ui'

type Panel = 'map' | 'phone' | 'cast' | null

/** The play screen (interaction-design.md §10.1): a top strip, the reading column, the input. */
export function Game({ intro }: { intro: Intro }) {
  const [panel, setPanel] = useState<Panel>(null)
  const [person, setPerson] = useState<CastCard['id'] | null>(null)
  const phase = useSessionStore((s) => s.phase)
  const passages = useSessionStore((s) => s.passages)
  const ended = phase === 'ended' || passages.at(-1)?.final === true

  return (
    <div className="stage play">
      <TopBar intro={intro} panel={panel} setPanel={setPanel} onPerson={setPerson} />
      <main className="reading">
        <Transcript onPerson={(who: Npc) => setPerson(who)} />
        {ended && <EndBlock />}
      </main>
      {!ended && <Composer />}
      {person && <CardModal card={intro.cast.find((c) => c.id === person)} onClose={() => setPerson(null)} />}
    </div>
  )
}

function TopBar({
  intro,
  panel,
  setPanel,
  onPerson,
}: {
  intro: Intro
  panel: Panel
  setPanel: (p: Panel) => void
  onPerson: (who: CastCard['id']) => void
}) {
  const room = useSessionStore((s) => s.room)
  const unseen = useSessionStore((s) => s.phoneUnseen)
  const wrap = useRef<HTMLDivElement>(null)
  const close = useCallback(() => setPanel(null), [setPanel])
  useDismiss(wrap, panel !== null, close)
  const toggle = (p: Exclude<Panel, null>) => {
    if (p === 'phone' && panel !== 'phone') openPhone()
    setPanel(panel === p ? null : p)
  }

  return (
    <header className="topbar">
      <div className="where">
        <span className="room">{room ? ROOM_NAME[room.player_room] : ''}</span>
        {room && room.present.length > 0 && (
          <span className="present">
            {room.present.map((who) => (
              <button key={who} type="button" className="link" onClick={() => onPerson(who)}>
                {PERSON_NAME[who]}
              </button>
            ))}
          </span>
        )}
      </div>
      <div className="tools" ref={wrap}>
        <button type="button" className="tool" aria-expanded={panel === 'map'} onClick={() => toggle('map')}>
          Map
        </button>
        <button type="button" className="tool" aria-expanded={panel === 'phone'} onClick={() => toggle('phone')}>
          Phone{unseen > 0 && <span className="dot" aria-label={`${unseen} new`} />}
        </button>
        <button type="button" className="tool" aria-expanded={panel === 'cast'} onClick={() => toggle('cast')}>
          People
        </button>
        {panel === 'map' && <MapPanel onGo={close} />}
        {panel === 'phone' && <PhonePanel onAct={close} />}
        {panel === 'cast' && <CastPanel intro={intro} />}
      </div>
    </header>
  )
}

/** The floor plan; only the room you are in is lit. Choosing a room writes the move into the box. */
function MapPanel({ onGo }: { onGo: () => void }) {
  const room = useSessionStore((s) => s.room)
  return (
    <div className="panel map-panel" role="dialog" aria-label="Map">
      <div className="map">
        <img src={artUrl('plan/apartment-floor-plan.png')} alt="Floor plan of the flat" />
        {MAP_ROOMS.map((r) => (
          <button
            key={r.room}
            type="button"
            className={`map-room${room?.player_room === r.room ? ' is-here' : ''}`}
            style={{ left: `${r.x}%`, top: `${r.y}%`, width: `${r.w}%`, height: `${r.h}%` }}
            aria-label={room?.player_room === r.room ? `${ROOM_NAME[r.room]}, you are here` : `Go to the ${ROOM_NAME[r.room].toLowerCase()}`}
            onClick={() => {
              if (room?.player_room !== r.room) useDraft.getState().put(`I go to the ${ROOM_NAME[r.room].toLowerCase()}.`)
              onGo()
            }}
          />
        ))}
      </div>
    </div>
  )
}

const PHONE_LABEL: Record<PhoneEvent['kind'], string> = {
  missed_call: 'Missed call',
  voicemail: 'Voicemail',
  text: 'Message',
  call_incoming: 'Calling',
  call_ended: 'Call ended',
}

function PhonePanel({ onAct }: { onAct: () => void }) {
  const phone = useSessionStore((s) => s.phone)
  return (
    <div className="panel phone-panel" role="dialog" aria-label="Phone">
      {phone.length === 0 && <p className="muted">Nothing new.</p>}
      <ul>
        {[...phone].reverse().map((e, i) => (
          <li key={`${e.id ?? i}-${e.kind}`} className={e.from === 'leo' ? 'from-leo' : undefined}>
            <span className="who">
              {PHONE_LABEL[e.kind]} from {PERSON_NAME[e.from]}
            </span>
            {e.kind === 'text' && e.text && <span className="body">{e.text}</span>}
            {e.kind === 'voicemail' && e.text && <span className="body">{e.text}</span>}
            {e.kind === 'voicemail' && !e.text && (
              <button
                type="button"
                className="link"
                onClick={() => {
                  useDraft.getState().put(`I listen to ${PERSON_NAME[e.from]}'s voicemail.`)
                  onAct()
                }}
              >
                Listen
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

function CastPanel({ intro }: { intro: Intro }) {
  const gender = useSessionStore((s) => s.gender)
  const name = useSessionStore((s) => s.name)
  const you = intro.player.cards.find((c) => c.gender === gender)
  return (
    <div className="panel cast-panel" role="dialog" aria-label="People">
      <div className="cast-strip">
        {intro.cast.map((c) => (
          <CastCardView key={c.id} card={c} />
        ))}
        {you && <CastCardView card={{ name, portrait: you.portrait, relation: intro.player.relation, memory: '' }} />}
      </div>
    </div>
  )
}

function CardModal({ card, onClose }: { card: CastCard | undefined; onClose: () => void }) {
  const box = useRef<HTMLDivElement>(null)
  useDismiss(box, true, onClose)
  if (!card) return null
  return (
    <div className="modal-scrim">
      <div className="modal" ref={box} role="dialog" aria-label={card.name}>
        <CastCardView card={card} />
        <button type="button" className="link" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  )
}

/** After the last passage: the truth on request, or another evening. */
function EndBlock() {
  const sessionId = useSessionStore((s) => s.sessionId)
  const [truth, setTruth] = useState<Truth | null>(null)
  const [error, setError] = useState<string | null>(null)
  const show = () => {
    if (!sessionId) return
    api.truth(sessionId).then(setTruth, () => setError('The story is still being saved. Try again in a moment.'))
  }
  return (
    <section className="column end">
      <p className="the-end">The end.</p>
      {!truth && (
        <div className="end-actions">
          <button type="button" className="action" onClick={show}>
            What really happened
          </button>
          <button type="button" className="link" onClick={leaveGame}>
            Play again
          </button>
        </div>
      )}
      {error && <p className="rejected">{error}</p>}
      {truth && (
        <div className="truth">
          <h2>{truth.title}</h2>
          <ol className="timeline">
            {truth.timeline.map((t) => (
              <li key={t.when}>
                <span className="when">{t.when}</span>
                <span>{t.what}</span>
              </li>
            ))}
          </ol>
          <ul className="shares">
            {truth.shares.map((s) => (
              <li key={s.who}>
                <strong>{s.who}</strong> {s.what}
              </li>
            ))}
          </ul>
          <button type="button" className="action" onClick={leaveGame}>
            Play again
          </button>
        </div>
      )}
    </section>
  )
}
