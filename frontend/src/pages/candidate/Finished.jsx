import { CheckCircle2, OctagonX } from 'lucide-react'
import { Link } from 'react-router-dom'
import { num, pct } from '../../lib/format'
import { Alert, Badge } from '../../ui'
import { Brand } from './Join'

export default function Finished({ state, result }) {
  const r = result || state.result || {}
  const terminated = r.status === 'terminated'
  const hasScore = r.score != null
  return (
    <div className="cand-wrap">
      <div className="cand-card wide" style={{ textAlign: 'center' }}>
        <Brand org={state.test.organization} />
        {terminated ? <OctagonX size={44} color="var(--bad)" style={{ margin: '16px auto 0' }} /> : <CheckCircle2 size={44} color="var(--ok)" style={{ margin: '16px auto 0' }} />}
        <h1 style={{ marginTop: 10 }}>{terminated ? 'Your test has ended' : 'Test submitted'}</h1>
        <p className="muted-2">{state.test.title}</p>
        {terminated && <Alert tone="bad" className="mt" >{r.terminated_reason || 'The test was ended by the proctoring rules or by the organizer.'} Your answers up to that point were saved. The organizer will contact you about the outcome.</Alert>}
        {r.auto_submitted && !terminated && <Alert tone="info" className="mt">Time ran out, so your answers were submitted automatically.</Alert>}
        {hasScore && !terminated && (
          <div className="scorebox"><div className="big">{num(r.score)}<span>/{num(r.max_score)}</span></div><div>{pct(r.percentage)}</div><div className="mt"><Badge status={r.passed ? 'pass' : 'fail'} /></div></div>
        )}
        {!hasScore && !terminated && <p className="mt">Thank you. Your answers were received{r.visibility === 'none' ? '. The organizer will share results with you.' : '.'}</p>}
        {r.review && (
          <div style={{ textAlign: 'left', marginTop: 24 }}><h3 className="mb">Answer review</h3>
            {r.review.map((q, i) => (
              <div key={q.question_id} className="review-q"><div><b>{i + 1}.</b> <span style={{ whiteSpace: 'pre-wrap' }}>{q.text}</span></div>
                <div className="sub" style={{ color: q.is_correct ? 'var(--ok)' : 'var(--bad)' }}>Your answer: {fmt(q.your_answer) || 'No answer'} {q.is_correct ? '✓' : '✗'}</div>
                {!q.is_correct && <div className="sub">Correct answer: {fmt(q.correct_answer)}</div>}{q.explanation && <div className="sub muted-2">{q.explanation}</div>}</div>))}</div>
        )}
        <p className="muted mt" style={{ fontSize: 13 }}>You can close this window.&nbsp;<Link to="/">Home</Link></p>
      </div>
    </div>
  )
}
const fmt = (v) => (Array.isArray(v) ? v.join(', ') : v ?? '')
