import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Button, Input, Modal, Select, Textarea, Alert, IconButton } from '../../ui'

export const TYPE_LABEL = { single: 'Single answer', multiple: 'Multiple answers', true_false: 'True / False', short_text: 'Short text' }

export function blankQuestion() {
  return { question_type: 'single', question_text: '', options: ['', '', '', ''], correct: [], marks: 1, negative_marks: 0, section: '', difficulty: 'medium', tags: [], explanation: '' }
}

// `onSave(body)` must return a promise; the modal closes when it resolves.
export default function QuestionEditor({ initial, onSave, onClose, sections = [], title }) {
  const [q, setQ] = useState(() => ({ ...blankQuestion(), ...initial, tags: initial?.tags || [], section: initial?.section || '', explanation: initial?.explanation || '' }))
  const [tags, setTags] = useState((initial?.tags || []).join(', '))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const type = q.question_type
  const set = (k, v) => setQ((p) => ({ ...p, [k]: v }))

  function changeType(t) {
    setQ((p) => ({ ...p, question_type: t, correct: [], options: t === 'true_false' ? ['True', 'False'] : t === 'short_text' ? [] : (p.options.length >= 2 && p.options[0] !== 'True' ? p.options : ['', '', '', '']) }))
  }
  const toggleCorrect = (i) => setQ((p) => ({ ...p, correct: type === 'multiple' ? (p.correct.includes(i) ? p.correct.filter((x) => x !== i) : [...p.correct, i]) : [i] }))
  const removeOption = (i) => setQ((p) => ({ ...p, options: p.options.filter((_, k) => k !== i), correct: p.correct.filter((c) => c !== i).map((c) => (c > i ? c - 1 : c)) }))

  async function save() {
    setErr('')
    const body = { ...q, tags: tags.split(',').map((t) => t.trim()).filter(Boolean), marks: Number(q.marks), negative_marks: Number(q.negative_marks) || 0, section: q.section.trim() || null, explanation: q.explanation.trim() || null }
    if (type === 'short_text') body.correct = (q.correctText ?? (q.correct || []).join('\n')).split('\n').map((s) => s.trim()).filter(Boolean)
    delete body.correctText; delete body.id; delete body.exam_id; delete body.position
    setBusy(true)
    try { await onSave(body); onClose() } catch (e) { setErr(e.message); setBusy(false) }
  }

  return (
    <Modal wide title={title || (initial?.id ? 'Edit question' : 'New question')} onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} onClick={save}>Save question</Button></>}>
      {err && <Alert tone="bad">{err}</Alert>}
      <div className="grid c3">
        <Select label="Type" value={type} onChange={(e) => changeType(e.target.value)}>{Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select>
        <Select label="Difficulty" value={q.difficulty} onChange={(e) => set('difficulty', e.target.value)}><option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option></Select>
        <div>
          <Input label="Section" list="sections" value={q.section} onChange={(e) => set('section', e.target.value)} placeholder="e.g. Aptitude" />
          <datalist id="sections">{sections.map((s) => <option key={s} value={s} />)}</datalist>
        </div>
      </div>
      <Textarea label="Question" rows={3} value={q.question_text} onChange={(e) => set('question_text', e.target.value)} />

      {(type === 'single' || type === 'multiple') && (
        <div className="field">
          <span className="label">Options — {type === 'multiple' ? 'tick every correct one' : 'select the correct one'}</span>
          {q.options.map((o, i) => (
            <div className="row" key={i} style={{ marginBottom: 6 }}>
              <input type={type === 'multiple' ? 'checkbox' : 'radio'} name="correct" checked={q.correct.includes(i)} onChange={() => toggleCorrect(i)} aria-label={`Option ${i + 1} is correct`} style={{ width: 18, height: 18, accentColor: 'var(--accent)' }} />
              <input className="input grow" value={o} placeholder={`Option ${i + 1}`} aria-label={`Option ${i + 1}`} onChange={(e) => setQ((p) => ({ ...p, options: p.options.map((x, k) => (k === i ? e.target.value : x)) }))} />
              <IconButton icon={Trash2} label="Remove option" disabled={q.options.length <= 2} onClick={() => removeOption(i)} />
            </div>
          ))}
          <div><Button size="sm" icon={Plus} disabled={q.options.length >= 8} onClick={() => set('options', [...q.options, ''])}>Add option</Button></div>
        </div>
      )}
      {type === 'true_false' && (
        <div className="field"><span className="label">The statement is</span>
          <div className="row">{['True', 'False'].map((v, i) => <label className="check" key={v}><input type="radio" name="tf" checked={q.correct[0] === i} onChange={() => set('correct', [i])} />{v}</label>)}</div></div>
      )}
      {type === 'short_text' && (
        <Textarea label="Accepted answers" rows={3} hint="One per line. Matching ignores capital letters and extra spaces." value={q.correctText ?? (q.correct || []).join('\n')} onChange={(e) => set('correctText', e.target.value)} />
      )}

      <div className="grid c3">
        <Input label="Marks" type="number" min="0.25" step="0.25" value={q.marks} onChange={(e) => set('marks', e.target.value)} />
        <Input label="Negative marks" type="number" min="0" step="0.25" value={q.negative_marks} onChange={(e) => set('negative_marks', e.target.value)} hint="Deducted for a wrong answer." />
        <Input label="Tags" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="comma, separated" />
      </div>
      <Textarea label="Explanation (shown in results when you allow it)" rows={2} value={q.explanation} onChange={(e) => set('explanation', e.target.value)} />
    </Modal>
  )
}
