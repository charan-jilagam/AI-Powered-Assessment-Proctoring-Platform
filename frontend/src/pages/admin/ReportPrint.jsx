import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Printer, ShieldCheck } from 'lucide-react'
import { api } from '../../lib/api'
import { duration, fmtDateTime, num, pct, toDate } from '../../lib/format'
import { useDocumentTitle } from '../../lib/hooks'
import { Async, Button, useLoad } from '../../ui'
import { Evidence } from './AttemptReport'

const RISK = { low: 'Low', medium: 'Medium', high: 'High' }
const CATEGORY = { browser: 'Browser & screen', device: 'Camera & microphone', audio: 'Audio', ai: 'AI vision', session: 'Session', admin: 'Proctor notes' }
const DECISION = { pending: 'Awaiting review', cleared: 'Cleared — no concern', suspicious: 'Suspicious — needs a second look', disqualified: 'Disqualified' }

const offset = (v, start) => {
  const s = start && v ? Math.max(0, Math.round((toDate(v) - toDate(start)) / 1000)) : null
  if (s == null) return '—'
  return `+${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

function Timeline({ a, events }) {
  const start = toDate(a.started_at)?.getTime()
  const end = Math.max(toDate(a.submitted_at)?.getTime() || 0, ...events.map((e) => toDate(e.created_at).getTime()))
  if (!start || !(end > start) || !events.length) return null
  const x = (t) => 12 + ((t - start) / (end - start)) * 576
  return (
    <figure className="rp-timeline">
      <svg viewBox="0 0 600 64" role="img" aria-label="Timeline of recorded events">
        <line x1="12" x2="588" y1="32" y2="32" className="axis" />
        {events.map((e) => { const cx = x(toDate(e.created_at).getTime()); return <g key={e.id}><line x1={cx} x2={cx} y1={e.severity === 2 ? 10 : 20} y2="32" className={`stem s${e.severity}`} /><circle cx={cx} cy={e.severity === 2 ? 10 : 20} r={e.severity === 2 ? 4.5 : 3.5} className={`rp-dot s${e.severity}`} /></g> })}
        <text x="12" y="58">Start</text><text x="588" y="58" textAnchor="end">{duration(Math.round((end - start) / 1000))}</text>
      </svg>
      <figcaption><span><i className="rp-dot s2" />Serious</span><span><i className="rp-dot s1" />Minor</span></figcaption>
    </figure>
  )
}

export default function ReportPrint() {
  const { id } = useParams()
  const state = useLoad(() => api.get(`/attempts/${id}`), [id])
  useDocumentTitle(state.data ? `${state.data.candidate.name} — assessment report` : 'Report')
  return <Async state={state}>{(a) => <Report a={a} />}</Async>
}

function Report({ a }) {
  const events = useMemo(() => a.violations.filter((v) => v.status !== 'dismissed'), [a])
  const byCat = useMemo(() => { const m = {}; events.forEach((v) => { m[v.category] = (m[v.category] || 0) + 1 }); return m }, [events])
  const serious = events.filter((v) => v.severity === 2)
  const withPhoto = serious.filter((v) => v.snapshot_id).slice(0, 8)
  const sections = useMemo(() => {
    const m = new Map()
    a.questions.forEach((q) => { const k = q.section || 'General'; const s = m.get(k) || { name: k, total: 0, correct: 0, awarded: 0, marks: 0 }; s.total++; s.correct += q.is_correct ? 1 : 0; s.awarded += q.awarded || 0; s.marks += q.marks || 0; m.set(k, s) })
    return [...m.values()]
  }, [a])
  const showKey = a.questions.some((q) => q.correct_answer != null)
  const fmt = (v) => (Array.isArray(v) ? v.join(', ') : v ?? '')
  const risk = a.risk_level || 'low'
  const final = a.status === 'submitted' || a.status === 'terminated'

  return (
    <div className="rp-wrap">
      <div className="rp-bar no-print">
        <Link to={`/app/attempts/${a.id}`} className="btn"><ArrowLeft size={16} />Back to attempt</Link>
        <Button variant="primary" icon={Printer} onClick={() => window.print()}>Print / Save as PDF</Button>
      </div>

      <article className="report" aria-label="Assessment and proctoring report">
        <header className="rp-head">
          <div className="rp-brand"><img className="mark-img" src="/brand/orvexa-emblem.png" alt="" width="34" height="34" /><div><b>{a.organization || 'ORVEXA'}</b><small>Assessment &amp; Proctoring Report</small></div></div>
          <dl className="rp-meta"><div><dt>Report ID</dt><dd>PA-{String(a.id).padStart(6, '0')}</dd></div><div><dt>Generated</dt><dd>{fmtDateTime(new Date().toISOString())}</dd></div></dl>
        </header>

        <section className="rp-hero">
          <div>
            <h1>{a.candidate.name}</h1>
            <p>{a.candidate.email}{a.attempt_no > 1 ? ` · attempt ${a.attempt_no}` : ''}</p>
            <p className="rp-test">{a.test.title}</p>
          </div>
          <div className={`rp-verdict ${a.review.status}`}><small>Review decision</small><b>{DECISION[a.review.status] || a.review.status}</b></div>
        </section>

        {a.terminated_reason && <p className="rp-callout bad"><b>Attempt ended early:</b> {a.terminated_reason}</p>}

        <section className="rp-tiles" aria-label="Summary">
          <div><span>Score</span><b>{a.score == null ? '—' : `${num(a.score)} / ${num(a.max_score)}`}</b><small>{a.percentage != null ? `${pct(a.percentage)} · pass mark ${a.test.pass_percentage}%` : 'Not scored'}</small></div>
          <div><span>Result</span><b className={a.final_result === 'pass' ? 'ok' : a.final_result === 'fail' ? 'bad' : ''}>{a.final_result ? (a.final_result === 'pass' ? 'Passed' : 'Failed') : '—'}</b><small>Rank {a.rank ?? '—'}</small></div>
          <div><span>Time taken</span><b>{duration(a.time_taken_seconds)}</b><small>of {a.test.duration_minutes} min</small></div>
          <div><span>Integrity risk</span><b className={`risk-${risk}`}>{RISK[risk]} · {a.risk_score}</b><small>{events.length} event{events.length === 1 ? '' : 's'}, {a.level2_count} serious</small></div>
        </section>

        <section>
          <h2>Integrity summary</h2>
          {events.length === 0 ? <p className="rp-muted">No proctoring events were recorded for this attempt.</p> : (
            <>
              <div className="rp-chips">{Object.entries(byCat).map(([k, n]) => <span key={k}>{CATEGORY[k] || k}<b>{n}</b></span>)}</div>
              <Timeline a={a} events={events} />
              <table className="rp-table"><thead><tr><th>Time</th><th>Event</th><th>Severity</th><th>Status</th></tr></thead><tbody>
                {events.map((v) => <tr key={v.id}><td className="mono">{offset(v.created_at, a.started_at)}</td><td><b>{v.label}</b>{v.details ? <div className="sub">{v.details}</div> : null}</td><td><span className={`pill s${v.severity}`}>{v.severity === 2 ? 'Serious' : 'Minor'}</span></td><td>{v.status === 'confirmed' ? 'Confirmed' : 'Open'}</td></tr>)}
              </tbody></table>
              {a.violations.length > events.length && <p className="rp-muted">{a.violations.length - events.length} event(s) were dismissed by a reviewer and are excluded from the risk score.</p>}
            </>
          )}
        </section>

        {withPhoto.length > 0 && (
          <section className="rp-keep">
            <h2>Evidence</h2>
            <div className="rp-evidence">{withPhoto.map((v) => (
              <figure key={v.id}><Evidence id={v.snapshot_id} alt={`Evidence: ${v.label}`} style={{ width: '100%', height: 'auto', aspectRatio: '4 / 3' }} /><figcaption><b>{v.label}</b><span>{offset(v.created_at, a.started_at)}</span></figcaption></figure>
            ))}</div>
          </section>
        )}

        {a.similarity?.length > 0 && (
          <section className="rp-keep">
            <h2>Code similarity</h2>
            <table className="rp-table"><thead><tr><th>Problem</th><th>Similar to</th><th>Match</th></tr></thead><tbody>
              {a.similarity.map((s, i) => <tr key={i}><td>{s.problem}</td><td>{s.other_candidate}</td><td><span className={`pill sim-${s.level}`}>{s.percent}% · {s.level}</span></td></tr>)}
            </tbody></table>
            <p className="rp-muted">Screening aid only: token-level comparison within this test. Short or standard solutions can legitimately match.</p>
          </section>
        )}

        {sections.length > 0 && (
          <section className="rp-keep">
            <h2>Performance by section</h2>
            <table className="rp-table"><thead><tr><th>Section</th><th className="num">Correct</th><th className="num">Marks</th></tr></thead><tbody>
              {sections.map((s) => <tr key={s.name}><td>{s.name}</td><td className="num">{s.correct} / {s.total}</td><td className="num">{num(s.awarded)} / {num(s.marks)}</td></tr>)}
            </tbody></table>
          </section>
        )}

        {a.coding.length > 0 && (
          <section className="rp-keep">
            <h2>Coding</h2>
            <table className="rp-table"><thead><tr><th>Problem</th><th>Language</th><th>Verdict</th><th className="num">Tests passed</th></tr></thead><tbody>
              {Object.values(a.coding.reduce((m, c) => { const b = m[c.problem]; if (!b || c.passed / (c.total || 1) >= b.passed / (b.total || 1)) m[c.problem] = c; return m }, {})).map((c) => <tr key={c.id}><td>{c.problem}</td><td>{c.language}</td><td>{c.verdict}</td><td className="num">{c.passed} / {c.total}</td></tr>)}
            </tbody></table>
            <p className="rp-muted">Best submission per problem. {a.coding.length} submission{a.coding.length === 1 ? '' : 's'} in total.</p>
          </section>
        )}

        {a.questions.length > 0 && (
          <section>
            <h2>Answers</h2>
            <table className="rp-table"><thead><tr><th style={{ width: 28 }}>#</th><th>Question</th><th>Answer</th>{showKey && <th>Correct</th>}<th className="num">Marks</th></tr></thead><tbody>
              {a.questions.map((q, i) => <tr key={q.question_id}><td className="mono">{i + 1}</td><td>{q.text}</td><td className={q.answered ? (q.is_correct ? 'ok' : 'bad') : 'rp-muted'}>{q.answered ? fmt(q.answer) : 'Not answered'}</td>{showKey && <td>{fmt(q.correct_answer)}</td>}<td className="num">{q.awarded == null ? '—' : num(q.awarded)} / {num(q.marks)}</td></tr>)}
            </tbody></table>
          </section>
        )}

        <section className="rp-keep">
          <h2>Session</h2>
          <dl className="rp-kv">
            <div><dt>Started</dt><dd>{fmtDateTime(a.started_at)}</dd></div><div><dt>Finished</dt><dd>{fmtDateTime(a.submitted_at)}</dd></div>
            <div><dt>IP address</dt><dd>{a.environment.ip_address || '—'}</dd></div><div><dt>Consent given</dt><dd>{fmtDateTime(a.environment.consent_at)}</dd></div>
            <div className="wide"><dt>Browser</dt><dd>{a.environment.user_agent || '—'}</dd></div>
          </dl>
        </section>

        {final && (
          <section className="rp-keep rp-decision">
            <h2>Reviewer decision</h2>
            <p><b>{DECISION[a.review.status]}</b>{a.review.reviewer ? ` — ${a.review.reviewer}, ${fmtDateTime(a.review.reviewed_at)}` : ''}</p>
            {a.review.note && <blockquote>{a.review.note}</blockquote>}
            <div className="rp-sign"><span>Reviewer signature</span><span>Date</span></div>
          </section>
        )}

        <footer className="rp-foot">Risk scores and proctoring events are evidence for human review, not proof of misconduct. Generated by ORVEXA · Report PA-{String(a.id).padStart(6, '0')}.</footer>
      </article>
    </div>
  )
}
