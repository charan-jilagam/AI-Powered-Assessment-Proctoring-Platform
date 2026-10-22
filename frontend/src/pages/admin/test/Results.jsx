import { Link, useNavigate } from 'react-router-dom'
import { Download } from 'lucide-react'
import { api } from '../../../lib/api'
import { duration, pct, num } from '../../../lib/format'
import { usePaged } from '../../../lib/hooks'
import { Badge, Button, Empty, Loading, Pager, Panel, RiskMeter, SearchBox, useUI } from '../../../ui'

export function resultBadge(a) {
  if (a.status === 'terminated') return <Badge status="terminated" />
  if (a.final_result) return <Badge status={a.final_result} />
  return <Badge status={a.status} dot />
}

export default function Results({ test: t }) {
  const { error } = useUI()
  const nav = useNavigate()
  const list = usePaged(`/tests/${t.id}/attempts`, { q: '', status: '', review_status: '', sort: 'recent', min_risk: '' })
  return (
    <>
      <div className="toolbar">
        <SearchBox value={list.filters.q} onChange={(v) => list.setFilter('q', v)} placeholder="Search name or e-mail" />
        <select className="input" aria-label="Status" value={list.filters.status} onChange={(e) => list.setFilter('status', e.target.value)}><option value="">All statuses</option><option value="submitted">Submitted</option><option value="terminated">Terminated</option><option value="in_progress">In progress</option><option value="registered">In lobby</option></select>
        <select className="input" aria-label="Review" value={list.filters.review_status} onChange={(e) => list.setFilter('review_status', e.target.value)}><option value="">Any review</option><option value="pending">Needs review</option><option value="cleared">Cleared</option><option value="suspicious">Suspicious</option><option value="disqualified">Disqualified</option></select>
        <select className="input" aria-label="Sort" value={list.filters.sort} onChange={(e) => list.setFilter('sort', e.target.value)}><option value="recent">Newest first</option><option value="score">Highest score</option><option value="risk">Highest risk</option><option value="name">Name</option></select>
        <Button className="right" icon={Download} onClick={() => api.download(`/tests/${t.id}/export.csv`, `${t.title.replace(/[^\w]+/g, '-')}-results.csv`).catch(error)}>Export CSV</Button>
      </div>
      <Panel flush>
        {list.loading && !list.data ? <Loading /> : !list.items.length ? <Empty title="No attempts match">Results appear here as candidates join and submit.</Empty> : (
          <div className="table-wrap"><table className="t"><thead><tr><th className="num">Rank</th><th>Candidate</th><th>Result</th><th className="num">Score</th><th className="num">Time</th><th>Risk</th><th>Review</th></tr></thead><tbody>
            {list.items.map((a) => (
              <tr key={a.id} className="click" onClick={() => nav(`/app/attempts/${a.id}`)}>
                <td className="num">{a.rank ?? '—'}</td>
                <td><Link className="name" to={`/app/attempts/${a.id}`} onClick={(e) => e.stopPropagation()}>{a.candidate.name}</Link>{a.attempt_no > 1 && <span className="sub"> · attempt {a.attempt_no}</span>}<div className="sub">{a.candidate.email}</div></td>
                <td>{resultBadge(a)}{a.auto_submitted && <div className="sub">auto-submitted</div>}</td>
                <td className="num">{a.score == null ? '—' : <>{num(a.score)}/{num(a.max_score)} <span className="muted">({pct(a.percentage)})</span></>}</td>
                <td className="num muted">{duration(a.time_taken_seconds)}</td>
                <td><RiskMeter score={a.risk_score} level={a.risk_level} /><div className="sub">{a.violation_count} flag{a.violation_count === 1 ? '' : 's'}</div></td>
                <td>{a.review_status === 'pending' ? <span className="muted">—</span> : <Badge status={a.review_status} />}</td></tr>))}
          </tbody></table></div>)}
        <Pager page={list.page} pageSize={list.pageSize} total={list.total} onPage={list.setPage} />
      </Panel>
    </>
  )
}
