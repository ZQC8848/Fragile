import { useEffect, useState } from 'react'
import { api, type Intro } from '../net/api'
import { startGame } from '../play/actions'
import { Game } from '../play/Game'
import { IntroFlow } from '../play/IntroFlow'
import { useSessionStore } from '../store/session'

/** Player-facing view (interaction-design.md §10): the four opening screens, then the evening. */
export function PlayRoute() {
  const [intro, setIntro] = useState<Intro | null>(null)
  const [error, setError] = useState<string | null>(null)
  const sessionId = useSessionStore((s) => s.sessionId)

  useEffect(() => {
    api.intro().then(setIntro, () => setError('The game server is not answering. Start the backend, then reload this page.'))
  }, [])

  if (error) {
    return (
      <div className="stage intro">
        <p className="column rejected">{error}</p>
      </div>
    )
  }
  if (!intro) return <div className="stage intro" aria-busy="true" />
  if (!sessionId) {
    return (
      <div className="stage">
        <IntroFlow intro={intro} onStart={startGame} />
      </div>
    )
  }
  return <Game intro={intro} />
}
