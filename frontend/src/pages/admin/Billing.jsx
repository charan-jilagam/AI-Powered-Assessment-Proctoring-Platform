import { useState } from 'react'
import { Check, CreditCard, ShieldCheck, X } from 'lucide-react'
import { api } from '../../lib/api'
import { fmtDate, limitText, money } from '../../lib/format'
import { useAuth } from '../../lib/auth'
import { useDocumentTitle } from '../../lib/hooks'
import { openCheckout } from '../../lib/razorpay'
import { Alert, Async, Badge, Button, Meter, PageHeader, Panel, useLoad, useUI } from '../../ui'

const FEATURES = [['ai_proctoring', 'AI face monitoring'], ['coding_enabled', 'Coding questions'], ['api_access', 'API keys'], ['webhooks_enabled', 'Webhooks']]

export default function Billing() {
  useDocumentTitle('Plan & usage')
  const { refresh } = useAuth()
  const { toast, error } = useUI()
  const org = useLoad(() => api.get('/org'), [])
  const bill = useLoad(() => api.get('/billing'), [])
  const [months, setMonths] = useState(1)
  const [busy, setBusy] = useState('')

  async function buy(plan) {
    setBusy(plan.code)
    try {
      const order = await api.post('/billing/order', { plan_code: plan.code, months })
      await openCheckout(order, {
        onDismiss: () => setBusy(''),
        onPaid: async (r) => {
          try {
            await api.post('/billing/verify', r)
            toast(`${plan.name} plan is active. Thank you!`)
            await Promise.all([org.reload(), bill.reload(), refresh?.()])
          } catch (e) { error(e) } finally { setBusy('') }
        },
      })
    } catch (e) { error(e); setBusy('') }
  }

  return (
    <>
      <PageHeader title="Plan & usage" subtitle="What your subscription includes, how much you have used, and how to upgrade." />
      <Async state={org}>{(o) => (
        <>
          {o.status === 'trial' && <Alert tone="info">Trial ends <b>{fmtDate(o.trial_ends_at)}</b>. Pick a plan below to keep running tests.</Alert>}
          {o.block_reason && <Alert tone="bad">{o.block_reason}</Alert>}
          <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', alignItems: 'start' }}>
            <Panel title={`${o.plan.name} plan`} actions={<Badge status={o.status} />}>
              <p className="muted-2 mb">{o.plan.description}</p>
              <dl className="kv"><dt>Price</dt><dd>{o.plan.price_monthly ? `${money(o.plan.price_monthly, o.plan.currency)} / month` : 'Free'}</dd>{o.subscription_ends_at && <><dt>Paid until</dt><dd>{fmtDate(o.subscription_ends_at)}</dd></>}<dt>Evidence kept</dt><dd>{o.limits.evidence_retention_days} days</dd></dl>
              <h3 className="mt">Included features</h3>
              <ul style={{ listStyle: 'none', padding: 0, display: 'grid', gap: 8, marginTop: 10 }}>{FEATURES.map(([k, l]) => <li key={k} className="row" style={{ color: o.limits[k] ? undefined : 'var(--text-3)' }}>{o.limits[k] ? <Check size={16} color="var(--ok)" /> : <X size={16} />}{l}</li>)}</ul>
            </Panel>
            <Panel title="Usage">
              <div className="grid" style={{ gap: 20 }}>
                <Meter label="Team seats" used={o.usage.team_seats} limit={o.limits.max_admins} />
                <Meter label="Active tests" used={o.usage.active_tests} limit={o.limits.max_active_tests} />
                <Meter label="Candidates this month" used={o.usage.candidates_this_month} limit={o.limits.max_candidates_per_month} />
              </div>
              <p className="hint mt">Candidates are counted once per month when they first join a test.</p>
            </Panel>
          </div>
        </>
      )}</Async>

      <Async state={bill}>{(b) => (
        <>
          <div className="row between wrap mt-lg mb"><h2>Choose a plan</h2>
            <div className="seg" role="group" aria-label="Billing period">{b.month_choices.map((n) => <button key={n} type="button" className={months === n ? 'on' : ''} onClick={() => setMonths(n)}>{n} mo</button>)}</div>
          </div>
          {!b.enabled && <Alert tone="warn">Online payment is not switched on for this ORVEXA workspace yet. Ask your platform owner to add the Razorpay keys, or contact us to change plans.</Alert>}
          <div className="plan-grid">
            {b.plans.map((p) => {
              const current = org.data?.plan?.code === p.code && org.data?.status === 'active'
              return (
                <div key={p.id} className={`plan-card ${p.code === 'professional' ? 'featured' : ''}`}>
                  {p.code === 'professional' && <span className="ribbon">Most popular</span>}
                  <h3>{p.name}</h3>
                  <div className="price">{money(p.price_monthly, p.currency)}<small> / month</small></div>
                  <p className="muted-2" style={{ minHeight: 40 }}>{p.description}</p>
                  <ul>
                    <li><Check size={14} />{limitText(p.max_candidates_per_month)} candidates / month</li>
                    <li><Check size={14} />{limitText(p.max_active_tests)} active tests</li>
                    <li><Check size={14} />{limitText(p.max_admins)} team seats</li>
                    {p.ai_proctoring && <li><Check size={14} />AI proctoring</li>}
                    {p.coding_enabled && <li><Check size={14} />Coding questions</li>}
                    {p.api_access && <li><Check size={14} />API &amp; webhooks</li>}
                  </ul>
                  <Button variant="primary" block icon={CreditCard} busy={busy === p.code} disabled={!b.enabled || !!busy}
                    onClick={() => buy(p)}>{current ? 'Renew' : 'Pay'} {money(p.price_monthly * months, p.currency)}</Button>
                  <p className="hint" style={{ textAlign: 'center', marginTop: 8 }}>{months} month{months > 1 ? 's' : ''}{current ? ', added to your current period' : ''}</p>
                </div>
              )
            })}
          </div>
          <p className="muted row" style={{ fontSize: 12.5, marginTop: 14, gap: 6 }}><ShieldCheck size={14} />Payments are processed by Razorpay (UPI, cards, netbanking, wallets). ORVEXA never sees your card details. Need Enterprise terms? Contact us.</p>

          <Panel className="mt-lg" title="Payment history" flush>
            {b.payments.length === 0 ? <p className="muted" style={{ padding: 20 }}>No payments yet.</p> : (
              <div className="table-wrap"><table className="t"><thead><tr><th>Date</th><th>Plan</th><th>Period</th><th className="num">Amount</th><th>Status</th><th>Reference</th></tr></thead><tbody>
                {b.payments.map((p) => <tr key={p.id}><td>{fmtDate(p.paid_at || p.created_at)}</td><td>{p.plan}</td><td>{p.months} mo{p.period_end ? ` · until ${fmtDate(p.period_end)}` : ''}</td><td className="num">{money(p.amount, p.currency)}</td><td><Badge status={p.status} /></td><td className="mono muted">{p.payment_id || p.order_id}</td></tr>)}
              </tbody></table></div>)}
          </Panel>
        </>
      )}</Async>
    </>
  )
}
