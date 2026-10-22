import { Link } from 'react-router-dom'
import { api } from '../../lib/api'
import { money, fmtDate } from '../../lib/format'
import { useDocumentTitle } from '../../lib/hooks'
import { Alert, Async, PageHeader, Panel, Stats, useLoad } from '../../ui'
import { LineChart, HBars, StackBar } from '../../ui/charts'

export default function Overview() {
  useDocumentTitle('Platform overview')
  const state = useLoad(() => api.get('/superadmin/overview'), [])
  return (
    <>
      <PageHeader title="Platform overview" subtitle="Every client organization at a glance." />
      <Async state={state}>{(d) => {
        const o = d.organizations
        const mrr = Object.entries(d.mrr || {}).map(([c, v]) => money(v, c)).join(' + ') || money(0)
        return (
          <>
            {d.new_demo_requests > 0 && <Alert tone="info"><Link to="/super/leads">{d.new_demo_requests} new demo request{d.new_demo_requests > 1 ? 's' : ''}</Link> waiting for a reply.</Alert>}
            <Stats items={[
              { value: o.total, label: 'Organizations', sub: `${o.active} active · ${o.trial} on trial` },
              { value: mrr, label: 'Monthly recurring', sub: 'From active plans (manual billing)' },
              { value: d.attempts.this_month, label: 'Attempts this month', sub: `${d.attempts.in_progress_now} in progress now` },
              { value: d.candidates, label: 'Candidates', sub: `${d.tests.published} of ${d.tests.total} tests published` },
            ]} />
            <div className="grid c2" style={{ alignItems: 'start' }}>
              <Panel title="Attempts, last 30 days"><LineChart data={d.attempts_last_30_days.map((x) => ({ label: x.date.slice(5), value: x.attempts }))} /></Panel>
              <Panel title="Organization status"><StackBar parts={[
                { label: 'Active', value: o.active, color: 'var(--ok)' }, { label: 'Trial', value: o.trial, color: 'var(--info)' },
                { label: 'Suspended', value: o.suspended, color: 'var(--warn)' }, { label: 'Cancelled', value: o.cancelled, color: 'var(--bad)' }]} /></Panel>
            </div>
            <div className="grid c2 mt" style={{ alignItems: 'start' }}>
              <Panel title="Busiest organizations (30 days)">
                {d.top_organizations.length ? <HBars items={d.top_organizations.map((t) => ({ label: t.name, value: t.attempts }))} /> : <p className="muted">No activity yet.</p>}
              </Panel>
              <Panel title="Trials ending soon">
                {d.trials_ending_soon.length ? <table className="t"><tbody>{d.trials_ending_soon.map((t) => (
                  <tr key={t.id}><td><Link className="name" to={`/super/organizations/${t.id}`}>{t.name}</Link></td><td className="num muted">{fmtDate(t.trial_ends_at)}</td></tr>))}</tbody></table> : <p className="muted">None in the next 7 days.</p>}
              </Panel>
            </div>
          </>
        )
      }}</Async>
    </>
  )
}
