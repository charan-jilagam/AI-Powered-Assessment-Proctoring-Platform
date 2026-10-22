import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../lib/api'
import { useDocumentTitle } from '../../lib/hooks'
import { Alert, Button, Input, PageHeader, Panel, Textarea, useUI } from '../../ui'

export default function TestNew() {
  useDocumentTitle('New test')
  const nav = useNavigate()
  const { error } = useUI()
  const [f, setF] = useState({ title: '', description: '', duration_minutes: 60, pass_percentage: 40 })
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  async function submit(e) {
    e.preventDefault(); setBusy(true)
    try {
      const t = await api.post('/tests', { title: f.title.trim(), description: f.description.trim() || null, duration_minutes: Number(f.duration_minutes), pass_percentage: Number(f.pass_percentage), questions: [] })
      nav(`/app/tests/${t.id}/questions`, { replace: true })
    } catch (x) { error(x); setBusy(false) }
  }
  return (
    <>
      <PageHeader title="New test" crumbs={[{ label: 'Tests', to: '/app/tests' }, { label: 'New' }]} subtitle="Start with the basics. You will add questions, proctoring and access rules next." />
      <form onSubmit={submit} style={{ maxWidth: 640 }}>
        <Panel>
          <Input label="Test title" required autoFocus value={f.title} onChange={set('title')} placeholder="e.g. Java Developer Screening — Round 1" />
          <Textarea label="Description" value={f.description} onChange={set('description')} hint="Candidates see this before they start." />
          <div className="grid c2"><Input label="Duration (minutes)" type="number" min="1" max="720" required value={f.duration_minutes} onChange={set('duration_minutes')} /><Input label="Passing score (%)" type="number" min="0" max="100" value={f.pass_percentage} onChange={set('pass_percentage')} /></div>
          <Alert tone="info">A unique test code is generated automatically. Candidates use it to sign in once you publish.</Alert>
          <Button variant="primary" type="submit" busy={busy}>Create and add questions</Button>
        </Panel>
      </form>
    </>
  )
}
