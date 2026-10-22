import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { api } from '../../lib/api'
import { fmtDate, limitText } from '../../lib/format'
import { useDocumentTitle, usePaged } from '../../lib/hooks'
import { Alert, Badge, Button, CopyButton, Empty, Input, Loading, Modal, PageHeader, Pager, Panel, SearchBox, Select, Textarea, useLoad, useUI } from '../../ui'

export function NewOrgModal({ onClose, onCreated }) {
  const { error } = useUI()
  const plans = useLoad(() => api.get('/superadmin/plans'), [])
  const [f, setF] = useState({ name: '', plan_code: 'trial', status: 'trial', admin_name: '', admin_email: '', contact_email: '', trial_days: '', admin_temp_password: '', internal_notes: '' })
  const [created, setCreated] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  async function submit(e) {
    e.preventDefault(); setBusy(true)
    const body = { ...f, trial_days: f.trial_days ? Number(f.trial_days) : undefined }
    Object.keys(body).forEach((k) => body[k] === '' && delete body[k])
    try { const r = await api.post('/superadmin/organizations', body); setCreated(r); onCreated?.(r) } catch (x) { error(x) } finally { setBusy(false) }
  }
  if (created) return (
    <Modal title="Organization created" onClose={onClose} footer={<Button variant="primary" onClick={onClose}>Done</Button>}>
      <Alert tone="ok"><b>{created.organization.name}</b> is ready on the {created.organization.plan_name} plan.</Alert>
      <p className="muted-2 mb">The admin <b>{created.admin.email}</b> activates their account with this one-time link{created.admin.temp_password ? ' (or signs in with the temporary password you set)' : ''}. An e-mail was also queued — see the outbox if SMTP is not configured.</p>
      <div className="row"><input className="input mono grow" readOnly value={created.admin.invite_url || ''} onFocus={(e) => e.target.select()} aria-label="Activation link" /><CopyButton text={created.admin.invite_url || ''} /></div>
    </Modal>
  )
  return (
    <Modal title="New organization" onClose={onClose} wide footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} onClick={submit}>Create organization</Button></>}>
      <form onSubmit={submit}>
        <div className="grid c2">
          <Input label="Organization name" required value={f.name} onChange={set('name')} />
          <Select label="Plan" value={f.plan_code} onChange={set('plan_code')}>{(plans.data || []).filter((p) => p.is_active).map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}</Select>
          <Select label="Starts as" value={f.status} onChange={set('status')}><option value="trial">Trial</option><option value="active">Active (paid)</option></Select>
          {f.status === 'trial' && <Input label="Trial length (days)" type="number" min="1" max="365" placeholder="Platform default" value={f.trial_days} onChange={set('trial_days')} />}
        </div>
        <h3 className="mt">First admin</h3>
        <p className="hint mb">This person manages the organization and creates tests.</p>
        <div className="grid c2">
          <Input label="Full name" required value={f.admin_name} onChange={set('admin_name')} />
          <Input label="E-mail" type="email" required value={f.admin_email} onChange={set('admin_email')} />
          <Input label="Temporary password (optional)" type="text" autoComplete="off" value={f.admin_temp_password} onChange={set('admin_temp_password')} hint="Leave empty to send an activation link instead." />
          <Input label="Billing contact (optional)" type="email" value={f.contact_email} onChange={set('contact_email')} />
        </div>
        <Textarea label="Internal notes" value={f.internal_notes} onChange={set('internal_notes')} hint="Only visible to platform staff." />
      </form>
    </Modal>
  )
}

export default function Orgs() {
  useDocumentTitle('Organizations')
  const nav = useNavigate()
  const list = usePaged('/superadmin/organizations', { q: '', status: '', plan: '' })
  const plans = useLoad(() => api.get('/superadmin/plans'), [])
  const [creating, setCreating] = useState(false)
  return (
    <>
      <PageHeader title="Organizations" subtitle="Client accounts. Each has its own admins, tests, candidates and limits."><Button variant="primary" icon={Plus} onClick={() => setCreating(true)}>New organization</Button></PageHeader>
      <div className="toolbar">
        <SearchBox value={list.filters.q} onChange={(v) => list.setFilter('q', v)} placeholder="Search by name or e-mail" />
        <select className="input" aria-label="Status" value={list.filters.status} onChange={(e) => list.setFilter('status', e.target.value)}><option value="">All statuses</option>{['trial', 'active', 'suspended', 'cancelled'].map((s) => <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>)}</select>
        <select className="input" aria-label="Plan" value={list.filters.plan} onChange={(e) => list.setFilter('plan', e.target.value)}><option value="">All plans</option>{(plans.data || []).map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}</select>
      </div>
      <Panel flush>
        {list.loading && !list.data ? <Loading /> : !list.items.length ? <Empty title="No organizations match" action={<Button variant="primary" onClick={() => setCreating(true)}>Create the first one</Button>}>Create a client organization and its first admin to get started.</Empty> : (
          <div className="table-wrap"><table className="t">
            <thead><tr><th>Organization</th><th>Plan</th><th>Status</th><th className="num">Seats</th><th className="num">Active tests</th><th className="num">Candidates / mo</th><th>Created</th></tr></thead>
            <tbody>{list.items.map((o) => (
              <tr key={o.id} className="click" onClick={() => nav(`/super/organizations/${o.id}`)}>
                <td><a className="name" href={`/super/organizations/${o.id}`} onClick={(e) => e.preventDefault()}>{o.name}</a><div className="sub">{o.contact_email}</div></td>
                <td>{o.plan_name}</td>
                <td><Badge status={o.status} />{o.status === 'trial' && o.trial_ends_at && <div className="sub">ends {fmtDate(o.trial_ends_at)}</div>}</td>
                <td className="num">{o.usage.team_seats}/{limitText(o.limits.max_admins)}</td>
                <td className="num">{o.usage.active_tests}/{limitText(o.limits.max_active_tests)}</td>
                <td className="num">{o.usage.candidates_this_month}/{limitText(o.limits.max_candidates_per_month)}</td>
                <td className="muted">{fmtDate(o.created_at)}</td>
              </tr>))}</tbody>
          </table></div>
        )}
        <Pager page={list.page} pageSize={list.pageSize} total={list.total} onPage={list.setPage} />
      </Panel>
      {creating && <NewOrgModal onClose={() => { setCreating(false); list.reload() }} />}
    </>
  )
}
