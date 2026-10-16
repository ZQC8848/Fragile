import { useState } from 'react'
import type { Gender } from '../protocol'
import { artUrl, type CastCard, type Intro } from '../net/api'

type Step = 'title' | 'premise' | 'cast' | 'you'

/** The four opening screens (interaction-design.md §10.4): title, premise, cast, your card. No skip. */
export function IntroFlow({ intro, onStart }: { intro: Intro; onStart: (name: string, gender: Gender) => void }) {
  const [step, setStep] = useState<Step>('title')

  if (step === 'title') {
    return (
      <main className="intro intro-title">
        <h1 className="stamp" aria-label={intro.title}>
          {intro.title}
        </h1>
        <button type="button" className="action" onClick={() => setStep('premise')} autoFocus>
          Begin
        </button>
      </main>
    )
  }

  if (step === 'premise') {
    return (
      <main className="intro">
        <div className="column prose">
          {intro.premise.map((p) => (
            <p key={p}>{p}</p>
          ))}
          <div className="intro-actions">
            <button type="button" className="action" onClick={() => setStep('cast')} autoFocus>
              Meet them
            </button>
          </div>
        </div>
      </main>
    )
  }

  if (step === 'cast') {
    return (
      <main className="intro">
        <div className="cast-grid">
          {intro.cast.map((c) => (
            <CastCardView key={c.id} card={c} />
          ))}
        </div>
        <div className="intro-actions">
          <button type="button" className="action" onClick={() => setStep('you')} autoFocus>
            And you
          </button>
        </div>
      </main>
    )
  }

  return <ChooseYou intro={intro} onStart={onStart} />
}

export function CastCardView({ card }: { card: Pick<CastCard, 'name' | 'portrait' | 'relation' | 'memory' | 'footer'> }) {
  return (
    <article className="cast-card" aria-label={card.name}>
      <img src={artUrl(card.portrait)} alt="" loading="lazy" />
      <h2>{card.name}</h2>
      <p className="relation">{card.relation}</p>
      {card.memory && <p className="memory">{card.memory}</p>}
      {card.footer && <p className="footer">{card.footer}</p>}
    </article>
  )
}

function ChooseYou({ intro, onStart }: { intro: Intro; onStart: (name: string, gender: Gender) => void }) {
  const [gender, setGender] = useState<Gender | null>(null)
  const [name, setName] = useState('')
  const start = () => gender && onStart(name.trim() || intro.player.default_name, gender)

  return (
    <main className="intro">
      <div className="column">
        <p className="prose">{intro.player.relation}</p>
      </div>
      <div className="you-grid" role="radiogroup" aria-label="Choose your card">
        {intro.player.cards.map((c) => (
          <button
            key={c.gender}
            type="button"
            role="radio"
            aria-checked={gender === c.gender}
            aria-label={c.gender === 'female' ? 'Woman' : 'Man'}
            className="you-card"
            onClick={() => setGender(c.gender)}
          >
            <img src={artUrl(c.portrait)} alt="" />
          </button>
        ))}
      </div>
      <form
        className="column name-row"
        onSubmit={(e) => {
          e.preventDefault()
          start()
        }}
      >
        <label htmlFor="player-name">Your name</label>
        <input
          id="player-name"
          value={name}
          maxLength={24}
          placeholder={intro.player.default_name}
          onChange={(e) => setName(e.target.value)}
          autoComplete="off"
        />
        <button type="submit" className="action" disabled={!gender}>
          Ring the bell
        </button>
      </form>
    </main>
  )
}
