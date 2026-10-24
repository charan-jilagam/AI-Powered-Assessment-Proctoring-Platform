import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AlertTriangle, ArrowRight, BarChart3, BookOpen, CircleCheck, FileText, MoreHorizontal, Plus, Trophy, UserRound, Users } from 'lucide-react'
import { api } from '../../lib/api'
import { ago, pct } from '../../lib/format'
import { useAuth } from '../../lib/auth'
import { useDocumentTitle, usePoll } from '../../lib/hooks'
import { Async, Avatar, Badge, Empty, Panel, RiskMeter, Stats, useLoad } from '../../ui'
import { LineChart } from '../../ui/charts'

function PlanRow({ icon: Icon, tone, label, used, limit }) {
  const unlimited = limit === -1
  const ratio = unlimited || !limit ? 0 : Math.min(1, used / limit)
  const color = { violet: 'var(--violet)', blue: 'var(--info)', green: 'var(--ok)' }[tone]
  const bg = { violet: 'var(--violet-soft)', blue: 'var(--info-soft)', green: 'var(--ok-soft)' }[tone]
  return (
    <div className="plan-row">
      <span className="ico" style={{ background: bg, color }}><Icon size={18} /></span>
      <div className="top"><span>{label}</span><span>{used} / {unlimited ? '∞' : limit}</span></div>
      <div className="meter"><i style={{ width: `${ratio * 100}%`, background: ratio >= 1 ? 'var(--bad)' : `linear-gradient(90deg, ${color}, ${color})` }} /></div>
    </div>
  )
}

export default function Dashboard() {
  useDocumentTitle('Dashboard')
  const { user, org } = useAuth()
  const nav = useNavigate()
  const [range, setRange] = useState(30)
  const state = useLoad(() => api.get(`/org/dashboard?range=${range}`), [range])
  usePoll(() => state.reload(), 20000)
  const first = user.full_name.split(' ')[0]
  return (
    <>
      <div className="page-head" style={{ alignItems: 'flex-start' }}>
        <div>
          <div className="hello">Welcome back, {first} <span aria-hidden>👋</span></div>
          <p className="hello-sub">{org?.status === 'trial' ? 'You are on a trial. Everything works; some limits are lower.' : "Here's what's happening with your assessments today."}</p>
        </div>
        {user.role === 'admin' && <div className="row"><Link className="btn primary" to="/app/tests/new"><Plus size={16} />New test</Link></div>}
      </div>
      <Async state={state}>{(d) => {
        const spark = d.attempts_per_day.map((x) => x.attempts)
        return (
          <>
            {d.awaiting_review > 0 && <div className="banner"><AlertTriangle size={18} /><span><Link to="/app/review">{d.awaiting_review} attempt{d.awaiting_review > 1 ? 's' : ''}</Link> with elevated risk need a human decision.</span><Link className="right row" style={{ gap: 4, fontWeight: 650 }} to="/app/review">Review now <ArrowRight size={14} /></Link></div>}
            <Stats items={[
              { icon: UserRound, tone: 'blue', value: d.in_progress_now, label: 'Taking a test now', live: true },
              { icon: BarChart3, tone: 'blue', value: d.attempts_last_30_days, label: `Attempts, ${d.range} days`, trend: d.trends.attempts, spark },
              { icon: Trophy, tone: 'violet', value: pct(d.average_percentage), label: 'Average score', trend: d.trends.average, spark },
              { icon: CircleCheck, tone: 'green', value: pct(d.pass_rate), label: 'Pass rate', trend: d.trends.pass_rate, spark },
              { icon: BookOpen, tone: 'indigo', value: `${d.tests.published ?? 0}/${d.tests.total}`, label: 'Tests published' },
            ]} />
            <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1.65fr) minmax(0, 1fr)', alignItems: 'start' }}>
              <Panel title="Attempts per day" actions={<div className="seg" role="group" aria-label="Range">{[7, 30, 90].map((n) => <button key={n} type="button" className={range === n ? 'on' : ''} onClick={() => setRange(n)}>{n}D</button>)}</div>}>
                <LineChart data={d.attempts_per_day.map((x) => ({ label: x.date.slice(5), value: x.attempts }))} />
              </Panel>
              <Panel title="Your plan" actions={user.role === 'admin' && <Link to="/app/billing" className="row" style={{ gap: 4, fontSize: 13, fontWeight: 600 }}>See plan details <ArrowRight size={13} /></Link>}>
                <PlanRow icon={FileText} tone="violet" label="Active tests" used={d.usage.active_tests} limit={d.limits.max_active_tests} />
                <PlanRow icon={Users} tone="blue" label="Candidates this month" used={d.usage.candidates_this_month} limit={d.limits.max_candidates_per_month} />
                <PlanRow icon={UserRound} tone="green" label="Team seats" used={d.usage.team_seats} limit={d.limits.max_admins} />
              </Panel>
            </div>
            <Panel className="mt" title="Latest attempts" actions={<Link className="btn sm outline-accent" to="/app/candidates">View all attempts <ArrowRight size={14} /></Link>} flush>
              {d.recent_attempts.length === 0 ? <Empty title="No attempts yet">Share a test code with candidates and their attempts show up here.</Empty> : (
                <div className="table-wrap"><table className="t"><thead><tr><th>Candidate</th><th>Test</th><th>Status</th><th>Score</th><th>Risk</th><th>Started</th><th className="num">Actions</th></tr></thead><tbody>
                  {d.recent_attempts.map((a) => (
                    <tr key={a.id} className="click" onClick={() => nav(`/app/attempts/${a.id}`)}>
                      <td><div className="row" style={{ gap: 12 }}><Avatar name={a.candidate_name} /><div><Link className="name" to={`/app/attempts/${a.id}`} onClick={(e) => e.stopPropagation()}>{a.candidate_name}</Link><div className="sub">{a.candidate_email}</div></div></div></td>
                      <td><Link to={`/app/tests/${a.test_id}`} onClick={(e) => e.stopPropagation()}>{a.test_title}</Link></td>
                      <td><Badge status={a.status} dot /></td>
                      <td style={{ fontWeight: 650 }}>{a.percentage == null ? '—' : pct(a.percentage)}</td>
                      <td><RiskMeter score={a.risk_score} /></td>
                      <td className="muted">{ago(a.started_at)}</td>
                      <td className="num"><Link className="btn sm icon-btn" to={`/app/attempts/${a.id}`} aria-label="Open report" onClick={(e) => e.stopPropagation()}><MoreHorizontal size={16} /></Link></td>
                    </tr>))}
                </tbody></table></div>)}
            </Panel>
          </>
        )
      }}</Async>
    </>
  )
}
