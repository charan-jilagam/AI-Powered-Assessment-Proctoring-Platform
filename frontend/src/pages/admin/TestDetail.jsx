import { lazy, Suspense, useState } from 'react'
import { NavLink, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { Archive, Copy, ExternalLink, Pause, Play, RefreshCw, Trash2, Undo2 } from 'lucide-react'
import { api } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { useDocumentTitle } from '../../lib/hooks'
import { Async, Badge, Button, CodeTicket, Loading, PageHeader, useLoad, useUI } from '../../ui'

const Overview = lazy(() => import('./test/Overview'))
const Questions = lazy(() => import('./test/Questions'))
const Coding = lazy(() => import('./test/Coding'))
const Settings = lazy(() => import('./test/Settings'))
const Invites = lazy(() => import('./test/Invites'))
const Results = lazy(() => import('./test/Results'))
const Live = lazy(() => import('./test/Live'))
const Analytics = lazy(() => import('./test/Analytics'))

export default function TestDetail() {
  const { id } = useParams()
  const nav = useNavigate()
  const { user } = useAuth()
  const { toast, error, confirm } = useUI()
  const state = useLoad(() => api.get(`/tests/${id}`), [id])
  const [busy, setBusy] = useState('')
  const isAdmin = user.role === 'admin'
  useDocumentTitle(state.data?.title)

  async function act(kind, label, confirmOpts) {
    if (confirmOpts && !(await confirm(confirmOpts))) return
    setBusy(kind)
    try {
      const r = await api.post(`/tests/${id}/${kind}`)
      toast(label)
      if (kind === 'duplicate') nav(`/app/tests/${r.id}`)
      else state.reload()
    } catch (e) { error(e) } finally { setBusy('') }
  }
  async function remove() {
    if (!(await confirm({ title: 'Delete this test?', message: 'Its questions are deleted too. Tests with candidate data cannot be deleted — archive them instead.', confirmLabel: 'Delete test', danger: true }))) return
    try { await api.del(`/tests/${id}`); toast('Test deleted'); nav('/app/tests', { replace: true }) } catch (e) { error(e) }
  }

  return (
    <Async state={state}>{(t) => {
      const ctx = { test: t, reload: state.reload, isAdmin }
      const tabs = [
        ['', 'Overview'], ['questions', `Questions (${t.question_count})`], ...(isAdmin ? [['coding', `Coding (${t.coding_problem_count})`]] : []),
        ...(isAdmin ? [['settings', 'Settings'], ['invites', 'Invites']] : []),
        ['results', `Results (${t.attempts_total})`], ['live', t.attempts.in_progress ? `Live (${t.attempts.in_progress})` : 'Live'], ['analytics', 'Analytics'],
      ]
      return (
        <>
          <PageHeader title={t.title} crumbs={[{ label: 'Tests', to: '/app/tests' }, { label: t.title }]}>
            <Badge status={t.status} />
            {isAdmin && t.status === 'draft' && <Button variant="primary" icon={Play} busy={busy === 'publish'} onClick={() => act('publish', 'Published — candidates can join with the code')}>Publish</Button>}
            {isAdmin && t.status === 'published' && <Button icon={Pause} busy={busy === 'close'} onClick={() => act('close', 'Closed to new candidates', { title: 'Close this test?', message: 'New candidates can no longer join. People already taking it can finish.', confirmLabel: 'Close test' })}>Close</Button>}
            {isAdmin && t.status === 'closed' && <Button icon={Play} onClick={() => act('publish', 'Reopened')}>Reopen</Button>}
            {isAdmin && (t.status === 'published' || t.status === 'closed') && t.attempts_total === 0 && <Button icon={Undo2} onClick={() => act('unpublish', 'Moved back to draft')}>Unpublish</Button>}
            {isAdmin && <Button icon={Copy} busy={busy === 'duplicate'} onClick={() => act('duplicate', 'Test duplicated')}>Duplicate</Button>}
          </PageHeader>
          <div className="row wrap mb" style={{ marginTop: -6 }}>
            <CodeTicket code={t.code} display={t.code_display} />
            <span className="muted-2" style={{ fontSize: 13 }}>or share <a href={t.join_url} target="_blank" rel="noreferrer">{t.join_url} <ExternalLink size={12} /></a></span>
            {isAdmin && <span className="right row">
              <Button size="sm" icon={RefreshCw} onClick={() => act('regenerate-code', 'New code generated', { title: 'Generate a new code?', message: 'The current code stops working immediately. Invitation links keep working.', confirmLabel: 'New code' })}>New code</Button>
              {t.status !== 'archived' && <Button size="sm" icon={Archive} onClick={() => act('archive', 'Archived', { title: 'Archive this test?', message: 'Candidates can no longer join. Results stay available.', confirmLabel: 'Archive' })}>Archive</Button>}
              <Button size="sm" variant="ghost" icon={Trash2} onClick={remove} aria-label="Delete test" />
            </span>}
          </div>
          <div className="tabs">{tabs.map(([to, label]) => <NavLink key={to} to={to ? `/app/tests/${id}/${to}` : `/app/tests/${id}`} end={!to} className={({ isActive }) => (isActive ? 'active' : '')}>{label}</NavLink>)}</div>
          <Suspense fallback={<Loading />}>
            <Routes>
              <Route index element={<Overview {...ctx} />} />
              <Route path="questions" element={<Questions {...ctx} />} />
              <Route path="coding" element={<Coding {...ctx} />} />
              <Route path="settings" element={<Settings {...ctx} />} />
              <Route path="invites" element={<Invites {...ctx} />} />
              <Route path="results" element={<Results {...ctx} />} />
              <Route path="live" element={<Live {...ctx} />} />
              <Route path="analytics" element={<Analytics {...ctx} />} />
            </Routes>
          </Suspense>
        </>
      )
    }}</Async>
  )
}
