import { useState } from 'react'
import { Plus } from 'lucide-react'
import { api } from '../../lib/api'
import { limitText, money } from '../../lib/format'
import { useDocumentTitle } from '../../lib/hooks'
import { Async, Badge, Button, Check_, Input, Modal, PageHeader, Panel, Textarea, useLoad, useUI } from '../../ui'

const EMPTY = { code: '', name: '', description: '', price_monthly: 0, currency: 'USD', max_admins: 3, max_active_tests: 3, max_candidates_per_month: 50, evidence_retention_days: 30, ai_proctoring: true, coding_enabled: true, api_access: false, webhooks_enabled: false, is_public: true, is_active: true, sort_order: 0 }

export default function Plans() {
  useDocumentTitle('Plans')
  const { toast, error, confirm } = useUI()
  const state = useLoad(() => api.get('/superadmin/plans'), [])
  const [editing, setEditing] = useState(null)
  return (
    <>
      <PageHeader title="Plans" subtitle="What each tier includes. Changing a plan changes every organization on it."><Button variant="primary" icon={Plus} onClick={() => setEditing({ ...EMPTY })}>New plan</Button></PageHeader>
      <Async state={state}>{(plans) => (
        <Panel flush><div className="table-wrap"><table className="t">
          <thead><tr><th>Plan</th><th className="num">Price</th><th className="num">Seats</th><th className="num">Tests</th><th className="num">Candidates/mo</th><th>Features</th><th className="num">Orgs</th><th /></tr></thead>
          <tbody>{plans.map((p) => (
            <tr key={p.id}><td><b>{p.name}</b> {!p.is_active && <Badge>Retired</Badge>} {!p.is_public && <Badge tone="info">Hidden</Badge>}<div className="sub"><code>{p.code}</code></div></td>
              <td className="num">{p.price_monthly ? money(p.price_monthly, p.currency) : 'Free'}</td><td className="num">{limitText(p.max_admins)}</td><td className="num">{limitText(p.max_active_tests)}</td><td className="num">{limitText(p.max_candidates_per_month)}</td>
              <td className="sub">{[p.ai_proctoring && 'AI', p.coding_enabled && 'Coding', p.api_access && 'API', p.webhooks_enabled && 'Webhooks'].filter(Boolean).join(', ') || '—'}</td>
              <td className="num">{p.organizations}</td>
              <td className="num nowrap"><Button size="sm" onClick={() => setEditing(p)}>Edit</Button>{' '}
                <Button size="sm" disabled={p.organizations > 0} title={p.organizations ? 'Move its organizations to another plan first' : ''} onClick={async () => { if (await confirm({ title: `Delete ${p.name}?`, message: 'This cannot be undone.', confirmLabel: 'Delete plan', danger: true })) { try { await api.del(`/superadmin/plans/${p.id}`); toast('Plan deleted'); state.reload() } catch (e) { error(e) } } }}>Delete</Button></td></tr>))}</tbody></table></div></Panel>
      )}</Async>
      {editing && <PlanEditor plan={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); state.reload() }} />}
    </>
  )
}

function PlanEditor({ plan, onClose, onSaved }) {
  const { toast, error } = useUI()
  const isNew = !plan.id
  const [f, setF] = useState(plan)
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const n = (k) => (e) => setF({ ...f, [k]: e.target.value === '' ? '' : Number(e.target.value) })
  const b = (k) => (e) => setF({ ...f, [k]: e.target.checked })
  async function save() {
    setBusy(true)
    const body = { ...f }; ['id', 'organizations'].forEach((k) => delete body[k])
    try { isNew ? await api.post('/superadmin/plans', body) : await api.put(`/superadmin/plans/${plan.id}`, body); toast('Plan saved'); onSaved() } catch (e) { error(e) } finally { setBusy(false) }
  }
  return (
    <Modal wide title={isNew ? 'New plan' : `Edit ${plan.name}`} onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} onClick={save}>Save plan</Button></>}>
      <div className="grid c2"><Input label="Name" value={f.name} onChange={set('name')} /><Input label="Code" value={f.code} onChange={set('code')} disabled={!isNew} hint="Lowercase letters, numbers, - and _. Cannot change later." /></div>
      <Textarea label="Description" value={f.description || ''} onChange={set('description')} />
      <div className="grid c3"><Input label="Price per month" type="number" min="0" value={f.price_monthly} onChange={n('price_monthly')} /><Input label="Currency" maxLength={3} value={f.currency} onChange={set('currency')} /><Input label="Sort order" type="number" value={f.sort_order} onChange={n('sort_order')} /></div>
      <div className="grid c4"><Input label="Team seats" type="number" min="-1" value={f.max_admins} onChange={n('max_admins')} /><Input label="Active tests" type="number" min="-1" value={f.max_active_tests} onChange={n('max_active_tests')} /><Input label="Candidates / month" type="number" min="-1" value={f.max_candidates_per_month} onChange={n('max_candidates_per_month')} /><Input label="Evidence days" type="number" min="1" value={f.evidence_retention_days} onChange={n('evidence_retention_days')} /></div>
      <p className="hint mb">-1 means unlimited.</p>
      <div className="grid c2">
        <Check_ label="AI proctoring" checked={f.ai_proctoring} onChange={b('ai_proctoring')} /><Check_ label="Coding questions" checked={f.coding_enabled} onChange={b('coding_enabled')} />
        <Check_ label="API access" checked={f.api_access} onChange={b('api_access')} /><Check_ label="Webhooks" checked={f.webhooks_enabled} onChange={b('webhooks_enabled')} />
        <Check_ label="Shown on the public pricing page" checked={f.is_public} onChange={b('is_public')} /><Check_ label="Available for new organizations" checked={f.is_active} onChange={b('is_active')} />
      </div>
    </Modal>
  )
}
