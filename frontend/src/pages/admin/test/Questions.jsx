import { useRef, useState } from 'react'
import { ArrowDown, ArrowUp, BookOpen, BookmarkPlus, Download, Pencil, Plus, Trash2, Upload } from 'lucide-react'
import { api } from '../../../lib/api'
import { Alert, Badge, Button, Empty, IconButton, Loading, Modal, Panel, SearchBox, useLoad, useUI } from '../../../ui'
import QuestionEditor, { TYPE_LABEL } from '../QuestionEditor'
import { usePaged } from '../../../lib/hooks'

export default function Questions({ test: t, reload, isAdmin }) {
  const { toast, error, confirm } = useUI()
  const state = useLoad(() => api.get(`/tests/${t.id}`), [t.id, t.question_count])
  const [editor, setEditor] = useState(null)
  const [csv, setCsv] = useState(false)
  const [bank, setBank] = useState(false)
  const questions = state.data?.questions || []
  const sections = [...new Set(questions.map((q) => q.section).filter(Boolean))]
  const locked = t.status === 'archived'
  const refresh = () => { state.reload(); reload() }

  async function move(i, dir) {
    const ids = questions.map((q) => q.id); const j = i + dir
    if (j < 0 || j >= ids.length) return
    ;[ids[i], ids[j]] = [ids[j], ids[i]]
    try { await api.post(`/tests/${t.id}/questions/reorder`, { ids }); state.reload() } catch (e) { error(e) }
  }
  const remove = async (q) => {
    if (!(await confirm({ title: 'Delete question?', message: 'Candidates who already started keep their copy; new candidates will not see it.', confirmLabel: 'Delete', danger: true }))) return
    try { await api.del(`/tests/${t.id}/questions/${q.id}`); refresh() } catch (e) { error(e) }
  }

  if (state.loading && !state.data) return <Loading />
  return (
    <>
      {isAdmin && !locked && (
        <div className="toolbar">
          <Button variant="primary" icon={Plus} onClick={() => setEditor({})}>Add question</Button>
          <Button icon={BookOpen} onClick={() => setBank(true)}>From question bank</Button>
          <Button icon={Upload} onClick={() => setCsv(true)}>Import CSV</Button>
          <span className="right muted" style={{ fontSize: 13 }}>{questions.length} question{questions.length === 1 ? '' : 's'} · {t.total_marks} marks</span>
        </div>
      )}
      {!questions.length ? <Panel><Empty title="No questions yet" action={isAdmin && <Button variant="primary" icon={Plus} onClick={() => setEditor({})}>Add the first question</Button>}>Write questions one by one, pull them from your question bank, or import many from a CSV file.</Empty></Panel> : (
        <Panel flush><ol style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {questions.map((q, i) => (
            <li key={q.id} style={{ padding: '14px 18px', borderTop: i ? '1px solid var(--line)' : 0, display: 'grid', gridTemplateColumns: '28px 1fr auto', gap: 12 }}>
              <span className="muted" style={{ fontVariantNumeric: 'tabular-nums', paddingTop: 2 }}>{i + 1}.</span>
              <div style={{ minWidth: 0 }}>
                <div style={{ whiteSpace: 'pre-wrap' }}>{q.question_text}</div>
                {q.options?.length > 0 && isAdmin && <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>{q.options.map((o, k) => <li key={k} style={{ color: q.correct.includes(k) ? 'var(--ok)' : 'var(--text-2)', fontWeight: q.correct.includes(k) ? 600 : 400 }}>{o}</li>)}</ul>}
                {q.question_type === 'short_text' && isAdmin && <div className="muted-2" style={{ marginTop: 6 }}>Accepts: {q.correct.join(' · ')}</div>}
                <div className="chips mt" style={{ marginTop: 10 }}>
                  <Badge tone="info">{TYPE_LABEL[q.question_type]}</Badge><Badge>{q.marks} mark{q.marks === 1 ? '' : 's'}</Badge>{q.negative_marks > 0 && <Badge tone="bad">−{q.negative_marks}</Badge>}
                  {q.section && <Badge>{q.section}</Badge>}<Badge>{q.difficulty}</Badge>{q.tags.map((x) => <Badge key={x}>#{x}</Badge>)}
                </div>
              </div>
              {isAdmin && !locked && <div className="row" style={{ alignSelf: 'start', gap: 2 }}>
                <IconButton icon={ArrowUp} label="Move up" disabled={i === 0} onClick={() => move(i, -1)} /><IconButton icon={ArrowDown} label="Move down" disabled={i === questions.length - 1} onClick={() => move(i, 1)} />
                <IconButton icon={Pencil} label="Edit" onClick={() => setEditor(q)} />
                <IconButton icon={BookmarkPlus} label="Save to question bank" onClick={async () => { try { await api.post(`/tests/${t.id}/questions/${q.id}/save-to-bank`); toast('Saved to the question bank') } catch (e) { error(e) } }} />
                <IconButton icon={Trash2} label="Delete" onClick={() => remove(q)} /></div>}
            </li>))}
        </ol></Panel>
      )}
      {editor && <QuestionEditor initial={editor.id ? editor : undefined} sections={sections} onClose={() => setEditor(null)}
        onSave={async (body) => { editor.id ? await api.put(`/tests/${t.id}/questions/${editor.id}`, body) : await api.post(`/tests/${t.id}/questions`, body); toast('Question saved'); refresh() }} />}
      {csv && <CsvImport testId={t.id} onClose={() => { setCsv(false); refresh() }} />}
      {bank && <BankPicker testId={t.id} onClose={() => { setBank(false); refresh() }} />}
    </>
  )
}

function CsvImport({ testId, onClose }) {
  const { error, toast } = useUI()
  const [file, setFile] = useState(null)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const input = useRef(null)
  async function send(dry) {
    setBusy(true)
    const fd = new FormData(); fd.append('file', file); fd.append('dry_run', dry ? 'true' : 'false')
    try { const r = await api.post(`/tests/${testId}/questions/import-csv`, fd); setResult({ ...r, dry }); if (!dry && !r.errors.length) { toast(`${r.imported} questions imported`); onClose() } } catch (e) { error(e) } finally { setBusy(false) }
  }
  return (
    <Modal wide title="Import questions from CSV" onClose={onClose} footer={<><Button onClick={onClose}>Close</Button><Button onClick={() => send(true)} disabled={!file} busy={busy}>Check file</Button><Button variant="primary" onClick={() => send(false)} disabled={!file || (result?.errors?.length > 0)} busy={busy}>Import</Button></>}>
      <p className="muted-2 mb">Columns: question_type, question_text, option_a…option_h, correct, marks, negative_marks, section, difficulty, tags, explanation. Either every row is imported or none is.</p>
      <div className="row mb"><Button icon={Download} onClick={() => api.download('/tests/questions-template.csv', 'questions-template.csv').catch(error)}>Download template</Button>
        <input ref={input} type="file" accept=".csv,text/csv" hidden onChange={(e) => { setFile(e.target.files[0]); setResult(null) }} />
        <Button icon={Upload} onClick={() => input.current.click()}>{file ? file.name : 'Choose CSV file'}</Button></div>
      {result?.errors?.length > 0 && <Alert tone="bad"><b>{result.errors.length} problem{result.errors.length > 1 ? 's' : ''} found — nothing was imported.</b><ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{result.errors.slice(0, 30).map((e, i) => <li key={i}>{typeof e === 'string' ? e : `Row ${e.row}: ${e.error || e.message}`}</li>)}</ul></Alert>}
      {result && !result.errors?.length && result.dry && <Alert tone="ok">{result.valid_rows} valid question{result.valid_rows === 1 ? '' : 's'}. Press Import to add them.</Alert>}
    </Modal>
  )
}

function BankPicker({ testId, onClose }) {
  const { error, toast } = useUI()
  const list = usePaged('/bank/questions', { q: '', difficulty: '', question_type: '' }, { pageSize: 50 })
  const [picked, setPicked] = useState(new Set())
  const [busy, setBusy] = useState(false)
  const toggle = (id) => setPicked((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  async function add() {
    setBusy(true)
    try { const r = await api.post(`/tests/${testId}/questions/from-bank`, { question_ids: [...picked] }); toast(`${r.added ?? picked.size} question${picked.size === 1 ? '' : 's'} added`); onClose() } catch (e) { error(e); setBusy(false) }
  }
  return (
    <Modal wide title="Add from question bank" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!picked.size} busy={busy} onClick={add}>Add {picked.size || ''} selected</Button></>}>
      <div className="toolbar"><SearchBox value={list.filters.q} onChange={(v) => list.setFilter('q', v)} placeholder="Search the bank" />
        <select className="input" aria-label="Difficulty" value={list.filters.difficulty} onChange={(e) => list.setFilter('difficulty', e.target.value)}><option value="">Any difficulty</option><option>easy</option><option>medium</option><option>hard</option></select></div>
      {list.loading && !list.data ? <Loading /> : !list.items.length ? <Empty title="The bank is empty">Save questions to the bank from any test, or add them under Question bank.</Empty> : (
        <div style={{ display: 'grid', gap: 2 }}>{list.items.map((q) => <label key={q.id} className="check" style={{ padding: '9px 6px', borderBottom: '1px solid var(--line)' }}><input type="checkbox" checked={picked.has(q.id)} onChange={() => toggle(q.id)} /><span>{q.question_text}<small>{TYPE_LABEL[q.question_type]} · {q.marks} mark{q.marks === 1 ? '' : 's'} · {q.difficulty}{q.section ? ` · ${q.section}` : ''}</small></span></label>)}</div>)}
    </Modal>
  )
}
