import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { api } from '../../../lib/api'
import { fromLocalInput, toLocalInput } from '../../../lib/format'
import { useAuth } from '../../../lib/auth'
import { Alert, Button, IconButton, Input, Panel, Select, Textarea, Toggle, useUI } from '../../../ui'

export default function Settings({ test: t, reload }) {
  const { feature } = useAuth()
  const { toast, error } = useUI()
  const [f, setF] = useState(() => ({
    title: t.title, description: t.description || '', instructions: t.instructions || '', duration_minutes: t.duration_minutes,
    start_time: toLocalInput(t.start_time), end_time: toLocalInput(t.end_time), access_mode: t.access_mode, access_password: '', clear_password: false,
    questions_per_attempt: t.questions_per_attempt || '', shuffle_questions: t.shuffle_questions, shuffle_options: t.shuffle_options,
    pass_percentage: t.pass_percentage, result_visibility: t.result_visibility, proctoring: { ...t.proctoring }, candidate_fields: t.candidate_fields || [],
  }))
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const px = (k) => (v) => setF({ ...f, proctoring: { ...f.proctoring, [k]: v } })
  const P = f.proctoring
  const aiAllowed = feature('ai_proctoring')

  async function save() {
    setBusy(true)
    const body = {
      title: f.title.trim(), description: f.description, instructions: f.instructions, duration_minutes: Number(f.duration_minutes),
      access_mode: f.access_mode, questions_per_attempt: f.questions_per_attempt ? Number(f.questions_per_attempt) : 0,
      shuffle_questions: f.shuffle_questions, shuffle_options: f.shuffle_options, pass_percentage: Number(f.pass_percentage), result_visibility: f.result_visibility,
      proctoring: { ...P, max_level2_violations: Number(P.max_level2_violations), snapshot_interval_seconds: Number(P.snapshot_interval_seconds), analysis_interval_seconds: Number(P.analysis_interval_seconds) },
      candidate_fields: f.candidate_fields.filter((c) => c.label.trim()).map((c) => ({ ...c, key: c.key || c.label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|^(\d)/, 'f$1').slice(0, 30) })),
    }
    if (f.start_time || f.end_time) { body.start_time = fromLocalInput(f.start_time); body.end_time = fromLocalInput(f.end_time) } else body.clear_schedule = true
    if (f.clear_password) body.access_password = ''
    else if (f.access_password) body.access_password = f.access_password
    try { const r = await api.patch(`/tests/${t.id}`, body); toast('Settings saved'); r.warnings?.forEach((w) => toast(w, 'error')); reload() } catch (e) { error(e) } finally { setBusy(false) }
  }

  return (
    <div style={{ maxWidth: 820 }}>
      <Panel title="Details">
        <Input label="Title" value={f.title} onChange={set('title')} />
        <Textarea label="Description" value={f.description} onChange={set('description')} />
        <Textarea label="Instructions shown before the test" rows={4} value={f.instructions} onChange={set('instructions')} hint="Rules, allowed materials, how to get help." />
        <div className="grid c3"><Input label="Duration (minutes)" type="number" min="1" max="720" value={f.duration_minutes} onChange={set('duration_minutes')} /><Input label="Passing score (%)" type="number" min="0" max="100" value={f.pass_percentage} onChange={set('pass_percentage')} />
          <Select label="Candidates see" value={f.result_visibility} onChange={set('result_visibility')}><option value="none">Nothing after submitting</option><option value="score">Their score</option><option value="full">Score + answers review</option></Select></div>
      </Panel>
      <Panel title="Access" className="mt">
        <div className="grid c2">
          <Select label="Who can join" value={f.access_mode} onChange={set('access_mode')} hint={f.access_mode === 'invite' ? 'Only e-mail addresses you invite can enter the code.' : 'Anyone who has the code can join.'}><option value="code">Anyone with the code</option><option value="invite">Invited e-mails only</option></Select>
          <Input label={t.has_password ? 'Change access password' : 'Access password (optional)'} type="text" autoComplete="off" value={f.access_password} onChange={(e) => setF({ ...f, access_password: e.target.value, clear_password: false })} placeholder={t.has_password ? 'Leave empty to keep the current one' : ''} hint="A second secret shared separately from the code." />
          <Input label="Opens at" type="datetime-local" value={f.start_time} onChange={set('start_time')} hint="Candidates must start between these times. Leave both empty to keep it always open." />
          <Input label="Closes at" type="datetime-local" value={f.end_time} onChange={set('end_time')} hint="The last moment someone can start. Running attempts finish normally." />
        </div>
        {t.has_password && <label className="check mb"><input type="checkbox" checked={f.clear_password} onChange={(e) => setF({ ...f, clear_password: e.target.checked, access_password: '' })} />Remove the access password</label>}
      </Panel>
      <Panel title="Questions" className="mt">
        <Toggle title="Shuffle question order" desc="Each candidate gets a different order." checked={f.shuffle_questions} onChange={(v) => setF({ ...f, shuffle_questions: v })} />
        <Toggle title="Shuffle answer options" desc="Option order differs per candidate. Scoring is unaffected." checked={f.shuffle_options} onChange={(v) => setF({ ...f, shuffle_options: v })} />
        <div style={{ paddingTop: 12 }}><Input label="Questions drawn per candidate" type="number" min="0" value={f.questions_per_attempt} onChange={set('questions_per_attempt')} hint={`Leave empty to give everyone all ${t.question_count} questions. A smaller number draws a random subset from the pool.`} /></div>
      </Panel>
      <Panel title="Proctoring" className="mt">
        {!aiAllowed && <Alert tone="warn">AI face monitoring is not part of your plan. Browser-based checks still work.</Alert>}
        <Toggle title="Require webcam" desc="Candidates must allow the camera. Losing it is flagged." checked={P.webcam_required} onChange={px('webcam_required')} />
        <Toggle title="AI face monitoring" desc="Detects no face, several faces, looking away, covered camera. Findings go to a human reviewer." checked={P.ai_monitoring && aiAllowed} disabled={!aiAllowed} onChange={px('ai_monitoring')} />
        <Toggle title="Let AI findings end the exam" desc="Off by default: AI can be wrong, so by default it only flags for review." checked={P.ai_can_terminate} disabled={!aiAllowed || !P.ai_monitoring} onChange={px('ai_can_terminate')} />
        <Toggle title="Require microphone" desc="Needed for voice detection." checked={P.microphone_required} onChange={px('microphone_required')} />
        <Toggle title="Require fullscreen" desc="Leaving fullscreen is a serious flag." checked={P.fullscreen_required} onChange={px('fullscreen_required')} />
        <Toggle title="Verify identity before starting" desc="Candidate photographs their ID and face. Reviewers see both." checked={P.id_verification} onChange={px('id_verification')} />
        <Toggle title="Flag tab switching" checked={P.detect_tab_switch} onChange={px('detect_tab_switch')} />
        <Toggle title="Block copy, paste and right-click" checked={P.block_copy_paste} onChange={(v) => setF({ ...f, proctoring: { ...P, block_copy_paste: v, block_right_click: v } })} />
        <Toggle title="End the exam automatically" desc="After the number of serious flags below." checked={P.auto_terminate} onChange={px('auto_terminate')} />
        <div className="grid c3" style={{ paddingTop: 14 }}>
          <Input label="Serious flags before ending" type="number" min="1" max="20" value={P.max_level2_violations} onChange={(e) => px('max_level2_violations')(e.target.value)} />
          <Input label="Photo snapshot every (s)" type="number" min="0" max="600" value={P.snapshot_interval_seconds} onChange={(e) => px('snapshot_interval_seconds')(e.target.value)} hint="0 turns periodic snapshots off." />
          <Input label="AI check every (s)" type="number" min="2" max="30" value={P.analysis_interval_seconds} onChange={(e) => px('analysis_interval_seconds')(e.target.value)} />
        </div>
      </Panel>
      <Panel title="Candidate details" className="mt" actions={<Button size="sm" icon={Plus} onClick={() => setF({ ...f, candidate_fields: [...f.candidate_fields, { key: '', label: '', required: true }] })}>Add field</Button>}>
        <p className="muted-2 mb">Name and e-mail are always asked. Add what else you need, such as a roll number or department.</p>
        {!f.candidate_fields.length && <p className="muted">No extra fields.</p>}
        {f.candidate_fields.map((c, i) => (
          <div className="row" key={i} style={{ marginBottom: 8 }}>
            <input className="input grow" aria-label="Field label" placeholder="Label, e.g. Roll number" value={c.label} onChange={(e) => setF({ ...f, candidate_fields: f.candidate_fields.map((x, n) => (n === i ? { ...x, label: e.target.value } : x)) })} />
            <label className="check nowrap"><input type="checkbox" checked={c.required} onChange={(e) => setF({ ...f, candidate_fields: f.candidate_fields.map((x, n) => (n === i ? { ...x, required: e.target.checked } : x)) })} />Required</label>
            <IconButton icon={Trash2} label="Remove field" onClick={() => setF({ ...f, candidate_fields: f.candidate_fields.filter((_, n) => n !== i) })} />
          </div>))}
      </Panel>
      <div className="mt"><Button variant="primary" busy={busy} onClick={save}>Save settings</Button></div>
    </div>
  )
}
