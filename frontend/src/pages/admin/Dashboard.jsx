import { Link } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { api } from '../../lib/api'
import { ago, pct } from '../../lib/format'
import { useAuth } from '../../lib/auth'
import { useDocumentTitle, usePoll } from '../../lib/hooks'
import { Alert, Async, Badge, Empty, Meter, PageHeader, Panel, RiskMeter, Stats, useLoad } from '../../ui'
import { LineChart } from '../../ui/charts'

export default function Dashboard() {
  useDocumentTitle('Dashboard')
  const { user, org } = useAuth()
  const state = useLoad(() => api.get('/org/dashboard'), [])
  usePoll(() => state.reload(), 20000)
  return (
    <>
      <PageHeader title={`Welcome back, ${user.full_name.split(' ')[0]}`} subtitle={org?.status === 'trial' ? 'You are on a trial. Everything works; some limits are lower.' : undefined}>
        {user.role === 'admin' && <Link className="btn primary" to="/app/tests/new"><Plus size={16} />New test</Link>}
      </PageHeader>
      <Async state={state}>{(d) => (
        <>
          {d.awaiting_review > 0 && <Alert tone="warn"><Link to="/app/review">{d.awaiting_review} attempt{d.awaiting_review > 1 ? 's' : ''}</Link> with elevated risk need a human decision.</Alert>}
          <Stats items={[
            { value: d.in_progress_now, label: 'Taking a test now' },
            { value: d.attempts_last_30_days, label: 'Attempts, 30 days' },
            { value: pct(d.average_percentage), label: 'Average score' },
            { value: pct(d.pass_rate), label: 'Pass rate' },
            { value: `${d.tests.published}/${d.tests.total}`, label: 'Tests published' },
          ]} />
          <div className="grid c2" style={{ alignItems: 'start' }}>
            <Panel title="Attempts per day"><LineChart data={d.attempts_per_day.map((x) => ({ label: x.date.slice(5), value: x.attempts }))} /></Panel>
            <Panel title="Your plan">
              <div className="grid">
                <Meter label="Active tests" used={d.usage.active_tests} limit={d.limits.max_active_tests} />
                <Meter label="Candidates this month" used={d.usage.candidates_this_month} limit={d.limits.max_candidates_per_month} />
                <Meter label="Team seats" used={d.usage.team_seats} limit={d.limits.max_admins} />
              </div>
              {user.role === 'admin' && <p className="mt" style={{ fontSize: 13 }}><Link to="/app/billing">See plan details</Link></p>}
            </Panel>
          </div>
          <Panel className="mt" title="Latest attempts" flush>
            {d.recent_attempts.length === 0 ? <Empty title="No attempts yet">Share a test code with candidates and their attempts show up here.</Empty> : (
              <div className="table-wrap"><table className="t"><thead><tr><th>Candidate</th><th>Test</th><th>Status</th><th className="num">Score</th><th>Risk</th><th>Started</th></tr></thead><tbody>
                {d.recent_attempts.map((a) => (
                  <tr key={a.id}><td><Link className="name" to={`/app/attempts/${a.id}`}>{a.candidate_name}</Link><div className="sub">{a.candidate_email}</div></td>
                    <td><Link to={`/app/tests/${a.test_id}`}>{a.test_title}</Link></td><td><Badge status={a.status} dot /></td><td className="num">{a.percentage == null ? '—' : pct(a.percentage)}</td><td><RiskMeter score={a.risk_score} /></td><td className="muted">{ago(a.started_at)}</td></tr>))}
              </tbody></table></div>)}
          </Panel>
        </>
      )}</Async>
    </>
  )
}
