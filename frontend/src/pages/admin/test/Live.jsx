import { useState } from 'react'
import { Link } from 'react-router-dom'
import { MessageSquare, Clock, Power } from 'lucide-react'
import { api } from '../../../lib/api'
import { clock } from '../../../lib/format'
import { usePoll } from '../../../lib/hooks'
import { Async, Badge, Button, Empty, Modal, Panel, RiskMeter, Stats, Textarea, Input, useLoad, useUI } from '../../../ui'

export default function Live({ test: t }) {
  const { toast, error, confirm } = useUI()
  const state = useLoad(() => api.get(`/tests/${t.id}/live`), [t.id])
  usePoll(() => state.reload(), 5000)
  const [dlg, setDlg] = useState(null)

  const call = async (fn, msg) => { try { await fn(); toast(msg); state.reload() } catch (e) { error(e) } }
  return (
    <Async state={state}>{(d) => (
      <>
        <Stats items={[{ value: d.summary.in_progress, label: 'Taking the test' }, { value: d.summary.in_lobby, label: 'In the lobby' }, { value: d.summary.offline, label: 'Offline', sub: 'No signal for 30 s' }, { value: d.summary.high_risk, label: 'High risk' }]} />
        <p className="muted mb" style={{ fontSize: 13 }}>Updates every 5 seconds while this tab is open.</p>
        <Panel flush>
          {!d.items.length ? <Empty title="Nobody is in the test right now">Candidates appear here when they join with the code.</Empty> : (
            <div className="table-wrap"><table className="t"><thead><tr><th>Candidate</th><th>Status</th><th className="num">Progress</th><th className="num">Time left</th><th>Risk</th><th>Last flag</th><th /></tr></thead><tbody>
              {d.items.map((a) => (
                <tr key={a.id}>
                  <td><Link className="name" to={`/app/attempts/${a.id}`}>{a.candidate.name}</Link><div className="sub">{a.candidate.email}</div></td>
                  <td>{a.status === 'registered' ? <Badge status="registered" /> : a.online ? <Badge tone="ok" ><i className="dot live" />Online</Badge> : <Badge tone="warn">Offline {a.seconds_since_heartbeat != null ? `${a.seconds_since_heartbeat}s` : ''}</Badge>}</td>
                  <td className="num">{a.status === 'registered' ? '—' : `${a.answered}/${a.total_questions}`}</td>
                  <td className="num">{a.remaining_seconds != null ? clock(a.remaining_seconds) : '—'}</td>
                  <td><RiskMeter score={a.risk_score} level={a.risk_level} /><div className="sub">{a.level2_count} serious</div></td>
                  <td className="sub" style={{ maxWidth: 220 }}>{a.last_violation ? a.last_violation.label : '—'}</td>
                  <td className="num nowrap">{a.status === 'in_progress' && <>
                    <Button size="sm" icon={MessageSquare} onClick={() => setDlg({ kind: 'message', a })}>Message</Button>{' '}
                    <Button size="sm" icon={Clock} onClick={() => setDlg({ kind: 'extend', a })}>Add time</Button>{' '}
                    <Button size="sm" icon={Power} onClick={async () => { if (await confirm({ title: `End ${a.candidate.name}'s attempt?`, message: 'Their answers so far are submitted and scored, and the attempt is marked terminated.', confirmLabel: 'End attempt', danger: true })) setDlg({ kind: 'terminate', a }) }}>End</Button></>}</td></tr>))}
            </tbody></table></div>)}
        </Panel>
        {dlg?.kind === 'message' && <TextDialog title={`Message ${dlg.a.candidate.name}`} label="Message" cta="Send message" onClose={() => setDlg(null)} onSubmit={(v) => call(() => api.post(`/attempts/${dlg.a.id}/message`, { body: v }), 'Message sent')} />}
        {dlg?.kind === 'terminate' && <TextDialog title="Reason for ending" label="Reason (recorded and shown to the candidate)" cta="End attempt" danger onClose={() => setDlg(null)} onSubmit={(v) => call(() => api.post(`/attempts/${dlg.a.id}/terminate`, { reason: v }), 'Attempt ended')} />}
        {dlg?.kind === 'extend' && <ExtendDialog onClose={() => setDlg(null)} onSubmit={(m) => call(() => api.post(`/attempts/${dlg.a.id}/extend`, { minutes: m }), `Added ${m} minutes`)} />}
      </>
    )}</Async>
  )
}

export function TextDialog({ title, label, cta, danger, onClose, onSubmit }) {
  const [v, setV] = useState('')
  const [busy, setBusy] = useState(false)
  return <Modal title={title} onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant={danger ? 'danger' : 'primary'} busy={busy} disabled={!v.trim()} onClick={async () => { setBusy(true); await onSubmit(v.trim()); onClose() }}>{cta}</Button></>}>
    <Textarea label={label} rows={3} value={v} onChange={(e) => setV(e.target.value)} maxLength={500} /></Modal>
}
function ExtendDialog({ onClose, onSubmit }) {
  const [m, setM] = useState(10)
  return <Modal title="Add time" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={async () => { await onSubmit(Number(m)); onClose() }}>Add {m} minutes</Button></>}>
    <Input label="Minutes to add" type="number" min="1" max="240" value={m} onChange={(e) => setM(e.target.value)} hint="The candidate is notified automatically." /></Modal>
}
