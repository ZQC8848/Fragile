import { useEffect, useRef, useState } from 'react'
import type { Addressee, Channels } from '../protocol'
import { useSessionStore } from '../store/session'
import { useDraft } from './draft'
import { requestOptions, reviewLine, sameChannels, submitTurn } from './actions'
import { ADDRESSEES, PERSON_NAME } from './ui'

const EMPTY: Channels = { speech: '', action: '', expression: '', addressee: null }
const ADDRESSEE_LABEL: Record<Addressee, string> = { julian: 'Julian', mia: 'Mia', both: 'Julian and Mia', nora: 'Nora', self: 'Nobody' }

/** The input area (interaction-design.md §10.3): box or fields, the reviewed draft, rejections, moves. */
export function Composer() {
  const pending = useSessionStore((s) => s.pending)
  const reviewing = useSessionStore((s) => s.reviewing)
  const review = useSessionStore((s) => s.review)
  const ringing = useSessionStore((s) => s.ringing)
  const phase = useSessionStore((s) => s.phase)
  const lastError = useSessionStore((s) => s.lastError)
  const prefill = useDraft((s) => s.prefill)

  const [mode, setMode] = useState<'box' | 'fields'>('box')
  const [text, setText] = useState('')
  const [fields, setFields] = useState<Channels>(EMPTY)
  const [draft, setDraft] = useState<Channels | null>(null)
  const [askSilence, setAskSilence] = useState(false)
  const [optionSource, setOptionSource] = useState(false)
  const box = useRef<HTMLTextAreaElement>(null)

  const busy = Boolean(pending) || reviewing || phase !== 'playing'

  // a reviewed line comes back: accepted -> editable draft, rejected -> explanation and a suggestion
  useEffect(() => {
    if (review?.verdict === 'ok') setDraft({ ...EMPTY, ...review.channels })
  }, [review])

  useEffect(() => {
    if (prefill === null) return
    const t = useDraft.getState().take()
    if (t === null) return
    setMode('box')
    setDraft(null)
    setText(t)
    box.current?.focus()
  }, [prefill])

  useEffect(() => {
    if (!busy) box.current?.focus()
  }, [busy])

  const reset = () => {
    setText('')
    setFields(EMPTY)
    setDraft(null)
    setAskSilence(false)
    setOptionSource(false)
  }

  const sendBox = () => {
    if (!text.trim()) return setAskSilence(true)
    reviewLine(text)
  }

  const sendDraft = () => {
    if (!draft) return
    if (optionSource) submitTurn(draft, 'option_edited')
    else if (review && sameChannels(draft, { ...EMPTY, ...review.channels })) submitTurn(draft, 'typed_accepted', review.review_id)
    else submitTurn(draft, 'typed_edited', review?.review_id)
    reset()
  }

  const sendFields = () => {
    const filled = fields.speech?.trim() || fields.action?.trim() || fields.expression?.trim()
    if (!filled) return setAskSilence(true)
    submitTurn(fields, 'filled')
    reset()
  }

  const rejected = review?.verdict === 'rejected' ? review : null

  return (
    <div className="composer">
      <div className="column">
        {ringing && !busy && (
          <div className="ringing" role="alert">
            <span>Nora is calling.</span>
            <button type="button" className="link" onClick={() => useDraft.getState().put('I answer the call.')}>
              Answer
            </button>
            <button type="button" className="link" onClick={() => useDraft.getState().put('I decline the call.')}>
              Decline
            </button>
          </div>
        )}

        {rejected && (
          <div className="rejected" role="alert">
            <p>{rejected.message ?? 'That line cannot be played as written.'}</p>
            {rejected.rewrite && (
              <button
                type="button"
                className="link"
                onClick={() => {
                  setDraft({ ...EMPTY, ...rejected.rewrite })
                  useSessionStore.getState().clearReview()
                }}
              >
                Use the suggestion
              </button>
            )}
          </div>
        )}
        {lastError && !rejected && <p className="rejected">{lastError}</p>}

        <Moves disabled={busy} onPick={(c, edit) => (edit ? (setDraft({ ...EMPTY, ...c }), setOptionSource(true)) : submitTurn(c, 'option'))} />

        {askSilence ? (
          <div className="silence">
            <span>Say and do nothing this turn?</span>
            <button type="button" className="action" onClick={() => (submitTurn({}, 'filled'), reset())}>
              Stay silent
            </button>
            <button type="button" className="link" onClick={() => setAskSilence(false)}>
              Cancel
            </button>
          </div>
        ) : draft ? (
          <DraftEditor draft={draft} onChange={setDraft} onSend={sendDraft} onCancel={reset} translated={Boolean(review?.translated)} />
        ) : mode === 'box' ? (
          <form
            className="box"
            onSubmit={(e) => {
              e.preventDefault()
              sendBox()
            }}
          >
            <textarea
              ref={box}
              value={text}
              rows={2}
              disabled={busy}
              aria-label="What you say and do"
              placeholder={busy ? '' : 'Write what you say and do. Put spoken words in quotes.'}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  sendBox()
                }
              }}
            />
            <button type="submit" className="action" disabled={busy}>
              {reviewing ? 'Reading' : 'Send'}
            </button>
          </form>
        ) : (
          <form
            className="fields"
            onSubmit={(e) => {
              e.preventDefault()
              sendFields()
            }}
          >
            <ChannelFields value={fields} onChange={setFields} disabled={busy} />
            <button type="submit" className="action" disabled={busy}>
              Send
            </button>
          </form>
        )}

        <div className="composer-bar">
          <button type="button" className="link" disabled={busy} onClick={() => (setMode(mode === 'box' ? 'fields' : 'box'), setDraft(null))}>
            {mode === 'box' ? 'Use separate fields' : 'Use one box'}
          </button>
        </div>
      </div>
    </div>
  )
}

function Moves({ disabled, onPick }: { disabled: boolean; onPick: (c: Channels, edit: boolean) => void }) {
  const options = useSessionStore((s) => s.options)
  const loading = useSessionStore((s) => s.optionsLoading)
  return (
    <div className="moves">
      {!options && (
        <button type="button" className="link" disabled={disabled || loading} onClick={requestOptions}>
          {loading ? 'Thinking of moves' : 'Suggest moves'}
        </button>
      )}
      {options && (
        <ul>
          {options.map((o, i) => (
            <li key={i}>
              <button type="button" className="move" disabled={disabled} onClick={() => onPick(o, false)}>
                {[o.action, o.expression, o.speech ? `“${o.speech}”` : ''].filter(Boolean).join(' ')}
              </button>
              <button type="button" className="link" disabled={disabled} onClick={() => onPick(o, true)} aria-label="Edit this move">
                Edit
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function DraftEditor({
  draft,
  onChange,
  onSend,
  onCancel,
  translated,
}: {
  draft: Channels
  onChange: (c: Channels) => void
  onSend: () => void
  onCancel: () => void
  translated: boolean
}) {
  return (
    <form
      className="fields draft"
      onSubmit={(e) => {
        e.preventDefault()
        onSend()
      }}
    >
      <p className="muted">{translated ? 'Translated and split into parts. Change anything, then send.' : 'Split into parts. Change anything, then send.'}</p>
      <ChannelFields value={draft} onChange={onChange} autoFocus />
      <div className="draft-actions">
        <button type="submit" className="action">
          Send
        </button>
        <button type="button" className="link" onClick={onCancel}>
          Start over
        </button>
      </div>
    </form>
  )
}

function ChannelFields({ value, onChange, disabled, autoFocus }: { value: Channels; onChange: (c: Channels) => void; disabled?: boolean; autoFocus?: boolean }) {
  const set = (k: keyof Channels) => (e: { target: { value: string } }) => onChange({ ...value, [k]: e.target.value || (k === 'addressee' ? null : '') })
  return (
    <div className="channel-fields">
      <label>
        <span>Say</span>
        <input value={value.speech ?? ''} onChange={set('speech')} disabled={disabled} autoFocus={autoFocus} />
      </label>
      <label>
        <span>Do</span>
        <input value={value.action ?? ''} onChange={set('action')} disabled={disabled} />
      </label>
      <label>
        <span>Face</span>
        <input value={value.expression ?? ''} onChange={set('expression')} disabled={disabled} />
      </label>
      <label>
        <span>To</span>
        <select value={value.addressee ?? ''} onChange={set('addressee')} disabled={disabled}>
          <option value="">Whoever is listening</option>
          {ADDRESSEES.map((a) => (
            <option key={a} value={a}>
              {ADDRESSEE_LABEL[a] ?? PERSON_NAME[a as 'julian']}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
