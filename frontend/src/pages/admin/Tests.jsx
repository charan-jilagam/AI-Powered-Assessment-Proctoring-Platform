import { Link, useNavigate } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { fmtDateTime } from '../../lib/format'
import { useAuth } from '../../lib/auth'
import { useDocumentTitle, usePaged } from '../../lib/hooks'
import { Badge, CodeTicket, Empty, Loading, PageHeader, Pager, Panel, SearchBox } from '../../ui'

export default function Tests() {
  useDocumentTitle('Tests')
  const { user } = useAuth()
  const nav = useNavigate()
  const list = usePaged('/tests', { q: '', status: '' })
  const isAdmin = user.role === 'admin'
  return (
    <>
      <PageHeader title="Tests" subtitle="Each test has its own code. Candidates enter the code to sign in.">{isAdmin && <Link className="btn primary" to="/app/tests/new"><Plus size={16} />New test</Link>}</PageHeader>
      <div className="toolbar">
        <SearchBox value={list.filters.q} onChange={(v) => list.setFilter('q', v)} placeholder="Search tests" />
        <select className="input" aria-label="Status" value={list.filters.status} onChange={(e) => list.setFilter('status', e.target.value)}><option value="">All statuses</option>{['draft', 'published', 'closed', 'archived'].map((s) => <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>)}</select>
      </div>
      <Panel flush>
        {list.loading && !list.data ? <Loading /> : !list.items.length ? (
          <Empty title={list.filters.q || list.filters.status ? 'No tests match' : 'Create your first test'} action={isAdmin && !list.filters.q ? <Link className="btn primary" to="/app/tests/new">New test</Link> : null}>
            {list.filters.q || list.filters.status ? 'Try a different search or status.' : 'Add questions, publish it, and share the generated code with candidates.'}</Empty>
        ) : (
          <div className="table-wrap"><table className="t"><thead><tr><th>Test</th><th>Code</th><th>Status</th><th className="num">Questions</th><th className="num">Minutes</th><th className="num">Attempts</th><th>Window</th></tr></thead><tbody>
            {list.items.map((t) => (
              <tr key={t.id} className="click" onClick={() => nav(`/app/tests/${t.id}`)}>
                <td><Link className="name" to={`/app/tests/${t.id}`} onClick={(e) => e.stopPropagation()}>{t.title}</Link>{t.has_password && <span className="sub"> · password</span>}{t.access_mode === 'invite' && <span className="sub"> · invite only</span>}</td>
                <td onClick={(e) => e.stopPropagation()}><CodeTicket small code={t.code} display={t.code_display} /></td>
                <td><Badge status={t.status} /></td>
                <td className="num">{t.question_count}{t.coding_problem_count ? ` + ${t.coding_problem_count} coding` : ''}</td><td className="num">{t.duration_minutes}</td>
                <td className="num">{t.attempts_total}{t.attempts.in_progress ? <span className="badge info" style={{ marginLeft: 6 }}>{t.attempts.in_progress} live</span> : null}</td>
                <td className="muted">{t.start_time || t.end_time ? `${fmtDateTime(t.start_time)} → ${fmtDateTime(t.end_time)}` : 'Always open'}</td></tr>))}
          </tbody></table></div>)}
        <Pager page={list.page} pageSize={list.pageSize} total={list.total} onPage={list.setPage} />
      </Panel>
    </>
  )
}
