import { Link, useNavigate } from 'react-router-dom'
import { ago } from '../../lib/format'
import { useDocumentTitle, usePaged } from '../../lib/hooks'
import { Badge, Empty, Loading, PageHeader, Pager, Panel, RiskMeter } from '../../ui'

export default function ReviewQueue() {
  useDocumentTitle('Review queue')
  const nav = useNavigate()
  const list = usePaged('/review-queue', { min_risk: 15 })
  return (
    <>
      <PageHeader title="Review queue" subtitle="Finished attempts with elevated risk that nobody has decided on yet, riskiest first." />
      <div className="toolbar"><select className="input" aria-label="Minimum risk" value={list.filters.min_risk} onChange={(e) => list.setFilter('min_risk', e.target.value)}><option value="1">Any flags</option><option value="15">Medium risk and above</option><option value="40">High risk only</option></select></div>
      <Panel flush>
        {list.loading && !list.data ? <Loading /> : !list.items.length ? <Empty title="Nothing to review">Attempts show up here when proctoring raises enough flags.</Empty> : (
          <table className="t"><thead><tr><th>Candidate</th><th>Test</th><th>Outcome</th><th>Risk</th><th>Finished</th></tr></thead><tbody>
            {list.items.map((a) => <tr key={a.id} className="click" onClick={() => nav(`/app/attempts/${a.id}`)}><td><Link className="name" to={`/app/attempts/${a.id}`} onClick={(e) => e.stopPropagation()}>{a.candidate.name}</Link><div className="sub">{a.candidate.email}</div></td><td>{a.test.title}</td><td><Badge status={a.status} />{a.terminated_reason && <div className="sub">{a.terminated_reason}</div>}</td><td><RiskMeter score={a.risk_score} level={a.risk_level} /><div className="sub">{a.violation_count} flags</div></td><td className="muted">{ago(a.submitted_at)}</td></tr>)}
          </tbody></table>)}
        <Pager page={list.page} pageSize={list.pageSize} total={list.total} onPage={list.setPage} />
      </Panel>
    </>
  )
}
