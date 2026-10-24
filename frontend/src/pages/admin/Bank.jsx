import { useState } from 'react'
import { Library, Pencil, Plus, Trash2 } from 'lucide-react'
import { api } from '../../lib/api'
import { useDocumentTitle, usePaged } from '../../lib/hooks'
import { Badge, Empty, IconButton, Button, Loading, Modal, PageHeader, Pager, Panel, SearchBox, useLoad, useUI } from '../../ui'
import QuestionEditor, { TYPE_LABEL } from './QuestionEditor'

export default function Bank() {
  useDocumentTitle('Question bank')
  const { toast, error, confirm } = useUI()
  const list = usePaged('/bank/questions', { q: '', difficulty: '', question_type: '', tag: '' })
  const tags = useLoad(() => api.get('/bank/tags'), [])
  const [editor, setEditor] = useState(null)
  const [lib, setLib] = useState(false)
  return (
    <>
      <PageHeader title="Question bank" subtitle="Reusable questions. Pull them into any test; changes here never alter tests that already copied a question."><Button icon={Library} onClick={() => setLib(true)}>Starter library</Button><Button variant="primary" icon={Plus} onClick={() => setEditor({})}>New question</Button></PageHeader>
      <div className="toolbar">
        <SearchBox value={list.filters.q} onChange={(v) => list.setFilter('q', v)} placeholder="Search questions" />
        <select className="input" aria-label="Type" value={list.filters.question_type} onChange={(e) => list.setFilter('question_type', e.target.value)}><option value="">All types</option>{Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <select className="input" aria-label="Difficulty" value={list.filters.difficulty} onChange={(e) => list.setFilter('difficulty', e.target.value)}><option value="">Any difficulty</option><option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option></select>
        {(tags.data?.length > 0) && <select className="input" aria-label="Tag" value={list.filters.tag} onChange={(e) => list.setFilter('tag', e.target.value)}><option value="">Any tag</option>{tags.data.map((t) => <option key={t.tag ?? t} value={t.tag ?? t}>#{t.tag ?? t}</option>)}</select>}
      </div>
      <Panel flush>
        {list.loading && !list.data ? <Loading /> : !list.items.length ? <Empty title="No questions in the bank" action={<span className="row"><Button variant="primary" onClick={() => setLib(true)}>Import the starter library</Button><Button onClick={() => setEditor({})}>Add a question</Button></span>}>Build a library once, then assemble tests from it in seconds. You can also save any test question to the bank.</Empty> : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>{list.items.map((q, i) => (
            <li key={q.id} style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 12, padding: '14px 18px', borderTop: i ? '1px solid var(--line)' : 0 }}>
              <div><div style={{ whiteSpace: 'pre-wrap' }}>{q.question_text}</div><div className="chips" style={{ marginTop: 8 }}><Badge tone="info">{TYPE_LABEL[q.question_type]}</Badge><Badge>{q.marks} mark{q.marks === 1 ? '' : 's'}</Badge><Badge>{q.difficulty}</Badge>{q.section && <Badge>{q.section}</Badge>}{q.tags.map((x) => <Badge key={x}>#{x}</Badge>)}</div></div>
              <div className="row" style={{ gap: 2 }}><IconButton icon={Pencil} label="Edit" onClick={() => setEditor(q)} />
                <IconButton icon={Trash2} label="Delete" onClick={async () => { if (await confirm({ title: 'Delete from bank?', message: 'Tests that already use a copy are not affected.', confirmLabel: 'Delete', danger: true })) { try { await api.del(`/bank/questions/${q.id}`); list.reload() } catch (e) { error(e) } } }} /></div></li>))}</ul>)}
        <Pager page={list.page} pageSize={list.pageSize} total={list.total} onPage={list.setPage} />
      </Panel>
      {lib && <LibraryDialog onClose={(changed) => { setLib(false); if (changed) { list.reload(); tags.reload() } }} />}
      {editor && <QuestionEditor initial={editor.id ? editor : undefined} title={editor.id ? 'Edit bank question' : 'New bank question'} onClose={() => { setEditor(null); list.reload(); tags.reload() }}
        onSave={async (body) => { editor.id ? await api.put(`/bank/questions/${editor.id}`, body) : await api.post('/bank/questions', body); toast('Saved to the bank') }} />}
    </>
  )
}


function LibraryDialog({ onClose }) {
  const { toast, error } = useUI()
  const data = useLoad(() => api.get('/bank/library'), [])
  const [busy, setBusy] = useState('')
  const [changed, setChanged] = useState(false)
  const run = async (sections, key) => {
    setBusy(key)
    try { const r = await api.post('/bank/library/import', { sections }); toast(r.added ? `Added ${r.added} question${r.added === 1 ? '' : 's'} to your bank` : 'Everything here is already in your bank'); setChanged(r.added > 0 || changed); data.reload() }
    catch (e) { error(e) } finally { setBusy('') }
  }
  const rows = data.data?.sections || []
  const all = rows.reduce((n, r) => n + r.questions, 0), have = rows.reduce((n, r) => n + r.imported, 0)
  return (
    <Modal title="Starter question library" onClose={() => onClose(changed)} footer={<Button variant="primary" busy={busy === 'all'} disabled={!rows.length || have === all} onClick={() => run([], 'all')}>Import everything</Button>}>
      <p className="muted-2 mb">Ready-made, reviewed multiple-choice questions. Imported questions become yours to edit; importing twice never creates duplicates.</p>
      {data.loading && !data.data ? <Loading /> : rows.map((r) => (
        <div key={r.section} className="row between" style={{ padding: '10px 0', borderTop: '1px solid var(--line)' }}>
          <div><b>{r.section}</b><div className="muted" style={{ fontSize: 13 }}>{r.questions} questions · {r.imported} in your bank</div></div>
          <Button size="sm" busy={busy === r.section} disabled={r.imported === r.questions} onClick={() => run([r.section], r.section)}>{r.imported === r.questions ? 'Imported' : 'Import'}</Button>
        </div>))}
    </Modal>
  )
}
