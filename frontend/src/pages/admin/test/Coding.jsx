import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { api } from '../../../lib/api'
import { fmtDateTime } from '../../../lib/format'
import { useAuth } from '../../../lib/auth'
import { Alert, Async, Badge, Button, Check_, Empty, IconButton, Input, Modal, Panel, Tabs, Textarea, useLoad, useUI } from '../../../ui'

const blank = () => ({ title: '', statement: '', input_format: '', output_format: '', constraints: '', points: 10, time_limit_seconds: 2, memory_limit_mb: 256, test_cases: [{ input_data: '', expected_output: '', is_sample: true }, { input_data: '', expected_output: '', is_sample: false }] })

export default function Coding({ test: t, reload }) {
  const { feature } = useAuth()
  const { toast, error, confirm } = useUI()
  const [tab, setTab] = useState('problems')
  const problems = useLoad(() => api.get(`/tests/${t.id}/coding-problems`), [t.id])
  const subs = useLoad(() => (tab === 'subs' ? api.get(`/tests/${t.id}/coding-submissions`) : Promise.resolve([])), [t.id, tab])
  const [edit, setEdit] = useState(null)
  if (!feature('coding_enabled')) return <Alert tone="warn">Coding questions are not included in your plan. Contact your account manager to enable them.</Alert>
  return (
    <>
      <Alert tone="info">Candidate code runs in a Judge0 sandbox. If the platform owner has not connected Judge0, candidates see "execution service unavailable" when they run code.</Alert>
      <Tabs active={tab} onChange={setTab} tabs={[{ id: 'problems', label: 'Problems', count: problems.data?.length }, { id: 'subs', label: 'Submissions' }]} />
      {tab === 'problems' && <>
        <div className="toolbar"><Button variant="primary" icon={Plus} onClick={() => setEdit(blank())}>Add problem</Button></div>
        <Async state={problems}>{(rows) => !rows.length ? <Panel><Empty title="No coding problems">Add a problem with sample and hidden test cases. Candidates see samples only.</Empty></Panel> : rows.map((p) => (
          <Panel key={p.id} title={p.title} actions={<><Badge>{p.points} pts</Badge><IconButton icon={Trash2} label="Delete problem" onClick={async () => { if (await confirm({ title: 'Delete this problem?', message: 'Past submissions for it are removed too.', confirmLabel: 'Delete', danger: true })) { try { await api.del(`/coding-problems/${p.id}`); problems.reload(); reload() } catch (e) { error(e) } } }} /></>}>
            <p style={{ whiteSpace: 'pre-wrap' }}>{p.statement}</p>
            <p className="muted mt" style={{ fontSize: 13 }}>{p.test_cases.length} test cases ({p.test_cases.filter((c) => c.is_sample).length} sample) · {p.time_limit_seconds}s · {p.memory_limit_mb} MB</p>
          </Panel>))}</Async></>}
      {tab === 'subs' && <Async state={subs}>{(rows) => !rows.length ? <Panel><Empty title="No submissions yet" /></Panel> : (
        <Panel flush><div className="table-wrap"><table className="t"><thead><tr><th>Candidate</th><th>Problem</th><th>Language</th><th>Verdict</th><th className="num">Passed</th><th>When</th></tr></thead><tbody>
          {rows.map((s) => <tr key={s.id}><td>{s.candidate_name}<div className="sub">{s.candidate_email}</div></td><td>{s.problem_title}</td><td>{s.language}</td><td><Badge tone={s.passed === s.total ? 'ok' : 'warn'}>{s.verdict}</Badge></td><td className="num">{s.passed}/{s.total}</td><td className="muted">{fmtDateTime(s.created_at)}</td></tr>)}
        </tbody></table></div></Panel>)}</Async>}
      {edit && <ProblemForm initial={edit} onClose={() => setEdit(null)} onSave={async (body) => { await api.post(`/tests/${t.id}/coding-problems`, body); toast('Problem added'); problems.reload(); reload() }} />}
    </>
  )
}

function ProblemForm({ initial, onClose, onSave }) {
  const [p, setP] = useState(initial)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const set = (k) => (e) => setP({ ...p, [k]: e.target.value })
  const setCase = (i, k, v) => setP({ ...p, test_cases: p.test_cases.map((c, n) => (n === i ? { ...c, [k]: v } : c)) })
  async function save() {
    setBusy(true); setErr('')
    const body = { ...p, points: Number(p.points), time_limit_seconds: Number(p.time_limit_seconds), memory_limit_mb: Number(p.memory_limit_mb) }
    ;['input_format', 'output_format', 'constraints'].forEach((k) => !body[k] && delete body[k])
    try { await onSave(body); onClose() } catch (e) { setErr(e.message); setBusy(false) }
  }
  return (
    <Modal wide title="New coding problem" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} onClick={save}>Add problem</Button></>}>
      {err && <Alert tone="bad">{err}</Alert>}
      <Input label="Title" value={p.title} onChange={set('title')} />
      <Textarea label="Problem statement" rows={5} value={p.statement} onChange={set('statement')} />
      <div className="grid c2"><Textarea label="Input format" rows={2} value={p.input_format} onChange={set('input_format')} /><Textarea label="Output format" rows={2} value={p.output_format} onChange={set('output_format')} /></div>
      <Input label="Constraints" value={p.constraints} onChange={set('constraints')} />
      <div className="grid c3"><Input label="Points" type="number" min="1" value={p.points} onChange={set('points')} /><Input label="Time limit (s)" type="number" min="0.5" step="0.5" value={p.time_limit_seconds} onChange={set('time_limit_seconds')} /><Input label="Memory (MB)" type="number" min="32" value={p.memory_limit_mb} onChange={set('memory_limit_mb')} /></div>
      <h3 className="mt">Test cases</h3><p className="hint mb">Sample cases are shown to candidates and used by "Run". Hidden cases only count when they submit.</p>
      {p.test_cases.map((c, i) => (
        <div key={i} className="panel" style={{ padding: 12, marginBottom: 10 }}>
          <div className="grid c2"><Textarea label="Input" className="mono" rows={2} value={c.input_data} onChange={(e) => setCase(i, 'input_data', e.target.value)} /><Textarea label="Expected output" rows={2} value={c.expected_output} onChange={(e) => setCase(i, 'expected_output', e.target.value)} /></div>
          <div className="row between"><Check_ label="Sample (visible to candidates)" checked={c.is_sample} onChange={(e) => setCase(i, 'is_sample', e.target.checked)} /><Button size="sm" disabled={p.test_cases.length <= 1} onClick={() => setP({ ...p, test_cases: p.test_cases.filter((_, n) => n !== i) })}>Remove</Button></div>
        </div>))}
      <Button size="sm" icon={Plus} onClick={() => setP({ ...p, test_cases: [...p.test_cases, { input_data: '', expected_output: '', is_sample: false }] })}>Add test case</Button>
    </Modal>
  )
}
