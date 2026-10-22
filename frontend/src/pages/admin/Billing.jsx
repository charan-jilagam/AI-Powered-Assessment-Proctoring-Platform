import { Check, X } from 'lucide-react'
import { useAuth } from '../../lib/auth'
import { api } from '../../lib/api'
import { fmtDate, limitText, money } from '../../lib/format'
import { useDocumentTitle } from '../../lib/hooks'
import { Alert, Async, Badge, Meter, PageHeader, Panel, useLoad } from '../../ui'

export default function Billing() {
  useDocumentTitle('Plan & usage')
  const { org } = useAuth()
  const state = useLoad(() => api.get('/org'), [])
  return (
    <>
      <PageHeader title="Plan & usage" subtitle="What your subscription includes and how much you have used." />
      <Async state={state}>{(o) => (
        <>
          {o.status === 'trial' && <Alert tone="info">Trial ends <b>{fmtDate(o.trial_ends_at)}</b>. Contact your account manager to move to a paid plan.</Alert>}
          {o.block_reason && <Alert tone="bad">{o.block_reason}</Alert>}
          <div className="grid c2" style={{ alignItems: 'start' }}>
            <Panel title={`${o.plan.name} plan`} actions={<Badge status={o.status} />}>
              <p className="muted-2 mb">{o.plan.description}</p>
              <dl className="kv"><dt>Price</dt><dd>{o.plan.price_monthly ? `${money(o.plan.price_monthly, o.plan.currency)} / month` : 'Free'}</dd>{o.subscription_ends_at && <><dt>Paid until</dt><dd>{fmtDate(o.subscription_ends_at)}</dd></>}<dt>Evidence kept</dt><dd>{o.limits.evidence_retention_days} days</dd></dl>
              <h3 className="mt">Included features</h3>
              <ul style={{ listStyle: 'none', padding: 0, display: 'grid', gap: 8 }}>{[['ai_proctoring', 'AI face monitoring'], ['coding_enabled', 'Coding questions'], ['api_access', 'API keys'], ['webhooks_enabled', 'Webhooks']].map(([k, l]) => <li key={k} className="row" style={{ color: o.limits[k] ? undefined : 'var(--text-3)' }}>{o.limits[k] ? <Check size={16} color="var(--ok)" /> : <X size={16} />}{l}</li>)}</ul>
            </Panel>
            <Panel title="Usage">
              <div className="grid" style={{ gap: 20 }}>
                <Meter label="Team seats" used={o.usage.team_seats} limit={o.limits.max_admins} />
                <Meter label="Active tests" used={o.usage.active_tests} limit={o.limits.max_active_tests} />
                <Meter label="Candidates this month" used={o.usage.candidates_this_month} limit={o.limits.max_candidates_per_month} />
              </div>
              <p className="hint mt">Candidates are counted once per month when they first join a test. Limits: {limitText(o.limits.max_candidates_per_month)} candidates, {limitText(o.limits.max_active_tests)} active tests, {limitText(o.limits.max_admins)} seats.</p>
            </Panel>
          </div>
          <p className="muted mt" style={{ fontSize: 13 }}>Plan changes and invoices are handled by your {org.name === o.name ? 'account manager' : 'account manager'}. Online payment is not available yet.</p>
        </>
      )}</Async>
    </>
  )
}
