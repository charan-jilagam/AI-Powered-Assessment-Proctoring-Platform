import { useMemo } from 'react'
import { Download, X } from 'lucide-react'
import { Button, IconButton } from '../../ui'

/* A live OMR answer sheet. It is a second view of the same answers the question screen edits: filling a bubble here
   answers the question there and vice versa. Bubble A is always the first option the candidate sees for that
   question, so it matches the A/B/C/D keys shown beside each option. */

const optionLabels = (q) => (q.type === 'true_false' ? ['T', 'F'] : q.options.map((_, i) => String.fromCharCode(65 + i)))

const BLOCK = 10

const stamp = (iso) => {
  if (!iso) return { date: '—', time: '' }
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z')
  return { date: d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' }), time: d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) }
}

function Field({ label, value, wide }) {
  return <div className={`omr-field${wide ? ' wide' : ''}`}><span>{label}</span><b title={value || ''}>{value || '—'}</b></div>
}

export default function OmrSheet({ omr, questions, answers, current, flagged = [], onPick, onJump, onClose, onDownload, downloading }) {
  const when = stamp(omr.started_at)
  const answered = questions.filter((q) => answers[q.id] != null).length
  const blocks = useMemo(() => {
    const out = []
    for (let i = 0; i < questions.length; i += BLOCK) out.push(questions.slice(i, i + BLOCK).map((q, k) => ({ q, n: i + k })))
    return out
  }, [questions])

  return (
    <section className="omr" aria-label="OMR answer sheet">
      <header className="omr-top">
        <div className="omr-title">OMR answer sheet</div>
        <span className="omr-count">{answered}/{questions.length} marked</span>
        {onDownload && <Button size="sm" icon={Download} busy={downloading} onClick={onDownload}>PDF</Button>}
        {onClose && <IconButton icon={X} label="Close OMR sheet" onClick={onClose} />}
      </header>

      <div className="omr-paper">
        <div className="omr-inst">{omr.institute}</div>
        {omr.note && <div className="omr-note">{omr.note}</div>}
        <div className="omr-band">OMR ANSWER SHEET</div>
        <div className="omr-test"><b>{omr.test_title}</b>{omr.test_code && <span>Code {omr.test_code}</span>}</div>

        <div className="omr-fields">
          <Field label="Candidate name" value={omr.candidate.name} wide />
          <div className="omr-field setbox" aria-label={omr.paper_set ? `Question set ${omr.paper_set}` : undefined}>
            <span>Question set</span>
            {omr.sets ? <div className="omr-setrow">{omr.sets.split('').map((s) => <i key={s} className={`omr-bub sm${s === omr.paper_set ? ' on' : ''}`}>{s}</i>)}</div> : <b>—</b>}
          </div>
          <Field label="E-mail" value={omr.candidate.email} wide />
          <Field label="Phone" value={omr.candidate.phone} />
          {omr.candidate.fields.map((f) => <Field key={f.label} label={f.label} value={f.value} />)}
          <Field label="Date" value={when.date} />
          <Field label="Start time" value={when.time} />
          <Field label="Duration" value={omr.duration_minutes ? `${omr.duration_minutes} minutes` : ''} />
          <Field label="Questions" value={String(questions.length)} />
        </div>

        <p className="omr-help">Click a bubble to mark your answer, click it again to remove it. Questions marked <b>*</b> allow more than one answer. This sheet and the question screen always show the same answers.</p>

        <div className="omr-grid">
          {blocks.map((rows, bi) => (
            <div className="omr-block" key={bi}>
              {rows.map(({ q, n }) => {
                const cur = answers[q.id]
                const short = q.type === 'short_text'
                const labels = optionLabels(q)
                return (
                  <div key={q.id} className={`omr-row${n === current ? ' cur' : ''}${flagged.includes(q.id) ? ' flag' : ''}${n % 10 < 5 ? ' alt' : ''}`}>
                    <button type="button" className="omr-num" onClick={() => onJump(n)} aria-label={`Go to question ${n + 1}`}>{n + 1}{q.type === 'multiple' ? '*' : ''}</button>
                    {short
                      ? <span className="omr-written" title={cur || ''}>{cur ? `✎ ${cur}` : '✎ written answer'}</span>
                      : labels.map((label, i) => {
                        const opt = q.options[i]
                        const on = q.type === 'multiple' ? (cur || []).includes(opt) : cur === opt
                        return <button key={i} type="button" className={`omr-bub${on ? ' on' : ''}`} aria-pressed={on} aria-label={`Question ${n + 1}, option ${label}${q.type === 'true_false' ? ` (${opt})` : ''}`} onClick={() => onPick(q, i)}>{label}</button>
                      })}
                  </div>
                )
              })}
            </div>
          ))}
        </div>

        <div className="omr-legend"><span><i className="omr-bub sm on" />Marked</span><span><i className="omr-bub sm" />Not marked</span><span><i className="omr-cur" />Question on screen</span><span><i className="omr-flag" />Flagged</span></div>
        <div className="omr-ref">{omr.attempt_ref}</div>
      </div>
    </section>
  )
}
