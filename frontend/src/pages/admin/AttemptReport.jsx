import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Check, Clock, MessageSquare, Power, RotateCcw, X } from 'lucide-react'
import { api } from '../../lib/api'
import { duration, fmtDateTime, num, pct } from '../../lib/format'
import { useAuth } from '../../lib/auth'
import { useDocumentTitle } from '../../lib/hooks'
import { Alert, Async, Badge, Button, Modal, PageHeader, Panel, RiskMeter, Select, Stats, Tabs, Textarea, useLoad, useUI } from '../../ui'
import { TextDialog } from './test/Live'

export function Evidence({ id, alt, style, onOpen }) {
  const [url, setUrl] = useState(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let u; let live = true
    api.blobUrl(`/evidence/${id}`).then((x) => { u = x; if (live) setUrl(x) }).catch(() => live && setFailed(true))
    return () => { live = false; if (u) URL.revokeObjectURL(u) }
  }, [id])
  if (failed) return <div className="muted" style={{ fontSize: 12, padding: 8 }}>Image removed</div>
  if (!url) return <div style={{ width: 120, height: 90, background: 'var(--neutral-soft)', borderRadius: 6, ...style }} />
  return <img src={url} alt={alt} onClick={() => onOpen?.(url)} style={{ width: 120, height: 90, objectFit: 'cover', borderRadius: 6, cursor: onOpen ? 'zoom-in' : undefined, background: '#000', ...style }} />
}

const REVIEW = [['cleared', 'Cleared — no concern'], ['suspicious', 'Suspicious — needs a second look'], ['disqualified', 'Disqualified']]

export default function AttemptReport() {
  const { id } = useParams()
  const nav = useNavigate()
  const { user } = useAuth()
  const { toast, error, confirm } = useUI()
  const state = useLoad(() => api.get(`/attempts/${id}`), [id])
  const [tab, setTab] = useState('answers')
  const [dlg, setDlg] = useState(null)
  const [zoom, setZoom] = useState(null)
  useDocumentTitle(state.data ? `${state.data.candidate.name} — report` : 'Report')

  const run = async (fn, msg) => { try { await fn(); toast(msg); state.reload() } catch (e) { error(e) } }

  return (
    <Async state={state}>{(a) => {
      const live = a.status === 'in_progress'
      const final = a.status === 'submitted' || a.status === 'terminated'
      const open = a.violations.filter((v) => v.status !== 'dismissed')
      return (
        <>
          <PageHeader title={a.candidate.name} crumbs={[{ label: 'Tests', to: '/app/tests' }, { label: a.test.title, to: `/app/tests/${a.test.id}/results` }, { label: a.candidate.name }]} subtitle={`${a.candidate.email}${a.attempt_no > 1 ? ` · attempt ${a.attempt_no}` : ''}`}>
            <Badge status={a.status} dot />{a.final_result && <Badge status={a.final_result} />}
            {live && <><Button icon={MessageSquare} onClick={() => setDlg('message')}>Message</Button><Button icon={Clock} onClick={() => setDlg('extend')}>Add time</Button><Button variant="danger" icon={Power} onClick={() => setDlg('terminate')}>End attempt</Button></>}
            {a.can_void && a.status !== 'voided' && <Button icon={RotateCcw} onClick={async () => { if (await confirm({ title: 'Allow a retake?', message: 'This attempt is hidden from results and kept in the audit trail. The candidate can join again with the same code and e-mail.', confirmLabel: 'Allow retake', danger: true })) run(async () => { await api.post(`/attempts/${id}/void`); nav(`/app/tests/${a.test.id}/results`) }, 'Attempt voided') }}>Allow retake</Button>}
          </PageHeader>

          {a.terminated_reason && <Alert tone="bad"><b>Ended early:</b> {a.terminated_reason}</Alert>}
          <Stats items={[
            { value: a.score == null ? '—' : `${num(a.score)}/${num(a.max_score)}`, label: 'Score', sub: a.percentage != null ? `${pct(a.percentage)} · pass mark ${a.test.pass_percentage}%` : undefined },
            { value: a.rank ?? '—', label: 'Rank' }, { value: duration(a.time_taken_seconds), label: 'Time taken', sub: `of ${a.test.duration_minutes} min` },
            { value: <RiskMeter score={a.risk_score} level={a.risk_level} />, label: 'Risk', sub: `${open.length} flag${open.length === 1 ? '' : 's'}, ${a.level2_count} serious` },
          ]} />

          {final && (
            <Panel title="Review decision" className="mb" actions={a.review.status !== 'pending' && <Badge status={a.review.status} />}>
              <ReviewForm key={a.review.reviewed_at} current={a.review} onSave={(b) => run(() => api.post(`/attempts/${id}/review`, b), 'Decision saved')} />
              {a.review.reviewer && <p className="hint">Last decided by {a.review.reviewer}, {fmtDateTime(a.review.reviewed_at)}</p>}
            </Panel>
          )}

          <Tabs active={tab} onChange={setTab} tabs={[{ id: 'answers', label: 'Answers' }, { id: 'proctoring', label: 'Proctoring', count: open.length }, { id: 'snapshots', label: 'Photos', count: a.snapshots.length }, ...(a.coding.length ? [{ id: 'code', label: 'Code', count: a.coding.length }] : []), { id: 'env', label: 'Environment' }]} />

          {tab === 'answers' && <Panel flush><table className="t"><thead><tr><th style={{ width: 40 }}>#</th><th>Question</th><th>Candidate's answer</th>{a.questions.some((q) => q.correct_answer != null) && <th>Correct answer</th>}<th className="num">Marks</th></tr></thead><tbody>
            {a.questions.map((q, i) => {
              const fmt = (v) => (Array.isArray(v) ? v.join(', ') : v ?? '')
              return <tr key={q.question_id}><td className="muted">{i + 1}</td><td style={{ maxWidth: 420 }}><div style={{ whiteSpace: 'pre-wrap' }}>{q.text}</div><div className="sub">{q.section ? `${q.section} · ` : ''}{q.type}{q.flagged ? ' · flagged by candidate' : ''}</div></td>
                <td>{q.answered ? <span style={{ color: q.is_correct ? 'var(--ok)' : 'var(--bad)', fontWeight: 600 }}>{fmt(q.answer)}</span> : <span className="muted">Not answered</span>}</td>
                {a.questions.some((x) => x.correct_answer != null) && <td>{fmt(q.correct_answer)}{q.explanation && <div className="sub">{q.explanation}</div>}</td>}
                <td className="num">{q.awarded == null ? '—' : num(q.awarded)} <span className="muted">/ {num(q.marks)}</span></td></tr>
            })}</tbody></table></Panel>}

          {tab === 'proctoring' && (a.violations.length ? (
            <Panel flush><ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>{a.violations.map((v, i) => (
              <li key={v.id} style={{ display: 'grid', gridTemplateColumns: '130px 1fr auto', gap: 14, padding: '13px 18px', borderTop: i ? '1px solid var(--line)' : 0, opacity: v.status === 'dismissed' ? 0.5 : 1, alignItems: 'start' }}>
                <div>{v.snapshot_id ? <Evidence id={v.snapshot_id} alt={`Evidence for ${v.label}`} onOpen={setZoom} /> : <div className="muted" style={{ fontSize: 12 }}>No photo</div>}</div>
                <div><div className="row wrap" style={{ gap: 8 }}><b>{v.label}</b><Badge tone={v.severity === 2 ? 'bad' : 'warn'}>{v.severity === 2 ? 'Serious' : 'Minor'}</Badge><Badge>{v.category}</Badge>{v.status !== 'open' && <Badge status={v.status} />}</div>
                  <div className="sub" style={{ marginTop: 3 }}>{fmtDateTime(v.created_at)} · {v.details}</div></div>
                <div className="row" style={{ gap: 4 }}>
                  {v.status !== 'confirmed' && <Button size="sm" icon={Check} onClick={() => run(() => api.patch(`/violations/${v.id}`, { status: 'confirmed' }), 'Confirmed')}>Confirm</Button>}
                  {v.status !== 'dismissed' && <Button size="sm" icon={X} onClick={() => run(() => api.patch(`/violations/${v.id}`, { status: 'dismissed' }), 'Dismissed — risk recalculated')}>Dismiss</Button>}
                </div></li>))}</ul></Panel>
          ) : <Panel><p className="muted">No proctoring flags were raised. {a.status === 'registered' ? 'The candidate has not started.' : ''}</p></Panel>)}

          {tab === 'snapshots' && (a.snapshots.length ? <Panel><div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>{a.snapshots.map((s) => <figure key={s.id} style={{ margin: 0 }}><Evidence id={s.id} alt={`${s.kind} photo`} onOpen={setZoom} style={{ width: 160, height: 120 }} /><figcaption className="sub">{s.kind === 'id' ? 'ID document' : s.kind === 'face' ? 'Face photo' : 'Periodic'} · {fmtDateTime(s.created_at)}</figcaption></figure>)}</div></Panel> : <Panel><p className="muted">No photos stored for this attempt.</p></Panel>)}

          {tab === 'code' && a.coding.map((c) => <Panel key={c.id} title={c.problem} actions={<><Badge>{c.language}</Badge><Badge tone={c.passed === c.total ? 'ok' : 'warn'}>{c.passed}/{c.total} · {c.verdict}</Badge></>} className="mb"><pre style={{ margin: 0, overflow: 'auto', fontFamily: 'var(--font-mono)', fontSize: 13 }}>{c.source_code}</pre></Panel>)}

          {tab === 'env' && <Panel><dl className="kv"><dt>IP address</dt><dd>{a.environment.ip_address || '—'}</dd><dt>Browser</dt><dd>{a.environment.user_agent || '—'}</dd><dt>Consent given</dt><dd>{fmtDateTime(a.environment.consent_at)}</dd>
            {Object.entries(a.environment.system_info || {}).map(([k, v]) => [<dt key={k + 'k'}>{k}</dt>, <dd key={k + 'v'}>{String(v)}</dd>])}
            <dt>Started</dt><dd>{fmtDateTime(a.started_at)}</dd><dt>Finished</dt><dd>{fmtDateTime(a.submitted_at)}</dd></dl>
            {a.messages.length > 0 && <><h3 className="mt">Messages sent during the exam</h3>{a.messages.map((m, i) => <p key={i} className="muted-2">{fmtDateTime(m.created_at)} — {m.body}</p>)}</>}</Panel>}

          {dlg === 'message' && <TextDialog title={`Message ${a.candidate.name}`} label="Message" cta="Send message" onClose={() => setDlg(null)} onSubmit={(v) => run(() => api.post(`/attempts/${id}/message`, { body: v }), 'Message sent')} />}
          {dlg === 'terminate' && <TextDialog title="End this attempt" label="Reason (shown to the candidate)" cta="End attempt" danger onClose={() => setDlg(null)} onSubmit={(v) => run(() => api.post(`/attempts/${id}/terminate`, { reason: v }), 'Attempt ended')} />}
          {dlg === 'extend' && <Modal title="Add time" onClose={() => setDlg(null)} footer={<Button variant="primary" onClick={() => { run(() => api.post(`/attempts/${id}/extend`, { minutes: 10 }), 'Added 10 minutes'); setDlg(null) }}>Add 10 minutes</Button>}><p>The candidate is told automatically.</p></Modal>}
          {zoom && <Modal wide title="Evidence" onClose={() => setZoom(null)}><img src={zoom} alt="Evidence enlarged" style={{ width: '100%', borderRadius: 6 }} /></Modal>}
        </>
      )
    }}</Async>
  )
}

function ReviewForm({ current, onSave }) {
  const [status, setStatus] = useState(current.status === 'pending' ? 'cleared' : current.status)
  const [note, setNote] = useState(current.note || '')
  return (
    <div className="grid c2" style={{ alignItems: 'end' }}>
      <Select label="Decision" value={status} onChange={(e) => setStatus(e.target.value)}>{REVIEW.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
      <Textarea label="Note (kept with the record)" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
      <div><Button variant="primary" onClick={() => onSave({ status, note: note.trim() || null })}>Save decision</Button></div>
    </div>
  )
}
