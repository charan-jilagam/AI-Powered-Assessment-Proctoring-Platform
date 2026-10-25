import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { Ban, KeyRound, Pause, Play, Plus } from 'lucide-react'
import { api } from '../../lib/api'
import { fmtDate, fmtDateTime, limitText, toLocalInput, fromLocalInput } from '../../lib/format'
import { useDocumentTitle } from '../../lib/hooks'
import { Alert, Async, Badge, Button, Check_, Input, Meter, Modal, PageHeader, Panel, Select, Textarea, useLoad, useUI } from '../../ui'
import { AddStaffModal, LinkModal } from '../../ui/staff'

const LIMITS = [['max_admins', 'Team seats'], ['max_active_tests', 'Active tests'], ['max_candidates_per_month', 'Candidates per month'], ['evidence_retention_days', 'Evidence retention (days)']]
const FEATURES = [['ai_proctoring', 'AI proctoring'], ['coding_enabled', 'Coding questions'], ['api_access', 'API access'], ['webhooks_enabled', 'Webhooks']]

export default function OrgDetail() {
  const { id } = useParams()
  const { toast, error, confirm } = useUI()
  const state = useLoad(() => api.get(`/superadmin/organizations/${id}`), [id])
  const plans = useLoad(() => api.get('/superadmin/plans'), [])
  const [modal, setModal] = useState(null)
  useDocumentTitle(state.data?.name)

  const patch = async (body, msg = 'Saved') => { try { await api.patch(`/superadmin/organizations/${id}`, body); toast(msg); state.reload() } catch (e) { error(e) } }

  return (
    <Async state={state}>{(o) => (
      <>
        <PageHeader title={o.name} crumbs={[{ label: 'Organizations', to: '/super/organizations' }, { label: o.name }]} subtitle={`/${o.slug} · created ${fmtDate(o.created_at)}`}>
          <Badge status={o.status} />
          {o.status === 'suspended' || o.status === 'cancelled' ? <Button icon={Play} onClick={() => patch({ status: 'active' }, 'Reactivated')}>Reactivate</Button>
            : <Button icon={Pause} onClick={() => setModal('suspend')}>Suspend</Button>}
          {o.status !== 'cancelled' && <Button variant="danger" icon={Ban} onClick={async () => { if (await confirm({ title: 'Cancel this organization?', message: 'Candidates and staff lose access immediately. Data is kept and the organization can be reactivated.', confirmLabel: 'Cancel organization', danger: true })) { try { await api.del(`/superadmin/organizations/${id}`); toast('Organization cancelled'); state.reload() } catch (e) { error(e) } } }}>Cancel</Button>}
        </PageHeader>
        {o.block_reason && <Alert tone="warn">{o.block_reason}</Alert>}

        <div className="grid c2" style={{ alignItems: 'start' }}>
          <Panel title="Subscription" actions={<Button size="sm" onClick={() => setModal('plan')}>Edit</Button>}>
            <dl className="kv">
              <dt>Plan</dt><dd>{o.plan_name}</dd>
              <dt>Status</dt><dd><Badge status={o.status} /></dd>
              <dt>Trial ends</dt><dd>{fmtDate(o.trial_ends_at)}</dd>
              <dt>Paid until</dt><dd>{fmtDate(o.subscription_ends_at)}</dd>
              <dt>Billing contact</dt><dd>{o.contact_email || '—'}</dd>
              <dt>Candidates ever</dt><dd>{o.candidates}</dd>
            </dl>
            <Alert tone="info" className="mt">Billing is manual: set the plan and paid-until date here after you invoice the client.</Alert>
          </Panel>
          <Panel title="Usage vs. limits" actions={<Button size="sm" onClick={() => setModal('limits')}>Override limits</Button>}>
            <div className="grid">
              <Meter label="Team seats" used={o.usage.team_seats} limit={o.limits.max_admins} />
              <Meter label="Active tests" used={o.usage.active_tests} limit={o.limits.max_active_tests} />
              <Meter label="Candidates this month" used={o.usage.candidates_this_month} limit={o.limits.max_candidates_per_month} />
            </div>
            <div className="chips mt">{FEATURES.map(([k, l]) => <span key={k} className="chip" style={{ opacity: o.limits[k] ? 1 : 0.5 }}>{o.limits[k] ? '✓' : '✕'} {l}</span>)}</div>
            {Object.keys(o.limits_override || {}).length > 0 && <p className="hint mt">Custom overrides: {Object.entries(o.limits_override).map(([k, v]) => `${k}=${typeof v === 'number' ? limitText(v) : v}`).join(', ')}</p>}
          </Panel>
        </div>

        <Panel className="mt" title="E-mail domains" actions={<Button size="sm" onClick={() => setModal('domains')}>Edit</Button>}>
          {o.allowed_domains?.length ? <div className="chips">{o.allowed_domains.map((d) => <span key={d} className="chip">@{d}</span>)}</div> : <p className="muted-2">No restriction: team members may use any e-mail address.</p>}
          <p className="hint mt">{o.allowed_domains?.length ? `Admins and team members must use these domains (subdomains count). Candidates are ${o.candidate_domain_lock ? 'restricted to them as well' : 'not restricted unless the org admin turns the lock on'}.` : 'Add your client’s domains, for example sconexsoft.com, to keep accounts on company addresses.'}</p>
        </Panel>

        <Panel className="mt" title="Staff" actions={<Button size="sm" icon={Plus} onClick={() => setModal('staff')}>Add admin</Button>} flush>
          <div className="table-wrap"><table className="t"><thead><tr><th>Name</th><th>Role</th><th>Status</th><th>E-mail</th><th>Last sign-in</th><th /></tr></thead>
            <tbody>{o.users.map((u) => (
              <tr key={u.id}><td><b>{u.full_name}</b><div className="sub">{u.email}</div></td><td><Badge status={u.role} tone="info" /></td>
                <td>{u.is_active ? <Badge status="active" /> : <Badge status="suspended">Disabled</Badge>}</td><td>{u.email_verified ? <Badge tone="ok">Verified</Badge> : <Badge tone="warn">Not verified</Badge>}</td><td className="muted">{fmtDateTime(u.last_login_at)}</td>
                <td className="num nowrap">
                  {!u.email_verified && <><Button size="sm" onClick={async () => { try { await api.post(`/superadmin/organizations/${id}/users/${u.id}/send-verification`); toast('Verification e-mail sent') } catch (e) { error(e) } }}>Send verification</Button>{' '}
                  <Button size="sm" onClick={async () => { if (await confirm({ title: `Mark ${u.email} as verified?`, message: 'Only do this if you have confirmed the address another way. They will be able to create tests immediately.', confirmLabel: 'Mark verified' })) { try { await api.post(`/superadmin/organizations/${id}/users/${u.id}/verify-email`); toast('Marked as verified'); state.reload() } catch (e) { error(e) } } }}>Mark verified</Button>{' '}</>}
                  <Button size="sm" icon={KeyRound} onClick={async () => { try { const r = await api.post(`/superadmin/organizations/${id}/users/${u.id}/reset-link`); setModal({ link: r.reset_url, title: `Reset link for ${u.full_name}` }) } catch (e) { error(e) } }}>Reset link</Button>{' '}
                  <Button size="sm" onClick={async () => { try { await api.patch(`/superadmin/organizations/${id}/users/${u.id}`, { is_active: !u.is_active }); state.reload() } catch (e) { error(e) } }}>{u.is_active ? 'Disable' : 'Enable'}</Button>
                </td></tr>))}</tbody></table></div>
        </Panel>

        <div className="grid c2 mt" style={{ alignItems: 'start' }}>
          <Panel title="Internal notes" actions={<Button size="sm" onClick={() => setModal('notes')}>Edit</Button>}><p className="muted-2" style={{ whiteSpace: 'pre-wrap' }}>{o.internal_notes || 'No notes yet. Only platform staff see notes.'}</p></Panel>
          <Panel title="Recent activity" flush><table className="t"><tbody>{o.recent_activity.length ? o.recent_activity.map((a) => <tr key={a.id}><td><code>{a.action}</code><div className="sub">{a.actor_email || 'system'} {a.details ? `· ${a.details}` : ''}</div></td><td className="muted num nowrap">{fmtDateTime(a.created_at)}</td></tr>) : <tr><td className="muted">No activity yet.</td></tr>}</tbody></table></Panel>
        </div>

        {modal === 'suspend' && <SuspendModal onClose={() => setModal(null)} onSave={(reason) => { patch({ status: 'suspended', suspended_reason: reason }, 'Suspended'); setModal(null) }} />}
        {modal === 'plan' && <PlanModal org={o} plans={plans.data || []} onClose={() => setModal(null)} onSave={(b) => { patch(b); setModal(null) }} />}
        {modal === 'limits' && <LimitsModal org={o} onClose={() => setModal(null)} onSave={(b) => { patch({ limits_override: b }, 'Limits updated'); setModal(null) }} />}
        {modal === 'domains' && <DomainsModal org={o} onClose={() => setModal(null)} onSave={(b) => { patch(b, 'Domains saved'); setModal(null) }} />}
        {modal === 'notes' && <NotesModal org={o} onClose={() => setModal(null)} onSave={(v) => { patch({ internal_notes: v }); setModal(null) }} />}
        {modal === 'staff' && <AddStaffModal title={`Add a user to ${o.name}`} onClose={() => { setModal(null); state.reload() }} onSubmit={(b) => api.post(`/superadmin/organizations/${id}/admins`, b)} />}
        {modal?.link && <LinkModal title={modal.title} url={modal.link} onClose={() => setModal(null)} />}
      </>
    )}</Async>
  )
}

function SuspendModal({ onClose, onSave }) {
  const [reason, setReason] = useState('')
  return <Modal title="Suspend organization" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="danger" onClick={() => onSave(reason)}>Suspend</Button></>}>
    <p className="muted-2 mb">Staff and candidates are blocked until you reactivate the organization. Running exams cannot be saved.</p>
    <Textarea label="Reason (shown to the client)" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Invoice 1042 is overdue" />
  </Modal>
}
function NotesModal({ org, onClose, onSave }) {
  const [v, setV] = useState(org.internal_notes || '')
  return <Modal title="Internal notes" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={() => onSave(v)}>Save notes</Button></>}><Textarea value={v} onChange={(e) => setV(e.target.value)} rows={7} aria-label="Notes" /></Modal>
}
function PlanModal({ org, plans, onClose, onSave }) {
  const [f, setF] = useState({ plan_code: org.plan_code, status: org.status === 'suspended' || org.status === 'cancelled' ? 'active' : org.status, trial_ends_at: toLocalInput(org.trial_ends_at), subscription_ends_at: toLocalInput(org.subscription_ends_at), contact_email: org.contact_email || '' })
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  return <Modal title="Edit subscription" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={() => onSave({ plan_code: f.plan_code, status: f.status, trial_ends_at: fromLocalInput(f.trial_ends_at), subscription_ends_at: fromLocalInput(f.subscription_ends_at), contact_email: f.contact_email || undefined })}>Save</Button></>}>
    <Select label="Plan" value={f.plan_code} onChange={set('plan_code')}>{plans.map((p) => <option key={p.code} value={p.code}>{p.name}{p.is_active ? '' : ' (retired)'}</option>)}</Select>
    <Select label="Status" value={f.status} onChange={set('status')}><option value="trial">Trial</option><option value="active">Active (paid)</option></Select>
    <div className="grid c2"><Input label="Trial ends" type="datetime-local" value={f.trial_ends_at} onChange={set('trial_ends_at')} /><Input label="Paid until" type="datetime-local" value={f.subscription_ends_at} onChange={set('subscription_ends_at')} /></div>
    <Input label="Billing contact" type="email" value={f.contact_email} onChange={set('contact_email')} />
  </Modal>
}
function LimitsModal({ org, onClose, onSave }) {
  const ov = org.limits_override || {}
  const [lim, setLim] = useState(Object.fromEntries(LIMITS.map(([k]) => [k, ov[k] ?? ''])))
  const [feat, setFeat] = useState(Object.fromEntries(FEATURES.map(([k]) => [k, ov[k] ?? null])))
  const submit = () => {
    const out = {}
    LIMITS.forEach(([k]) => { if (lim[k] !== '' && lim[k] !== null) out[k] = Number(lim[k]) })
    FEATURES.forEach(([k]) => { if (feat[k] !== null) out[k] = feat[k] })
    onSave(out)
  }
  return <Modal title="Override plan limits" onClose={onClose} wide footer={<><Button onClick={() => { setLim(Object.fromEntries(LIMITS.map(([k]) => [k, '']))); setFeat(Object.fromEntries(FEATURES.map(([k]) => [k, null]))) }}>Clear all</Button><Button variant="primary" onClick={submit}>Save overrides</Button></>}>
    <p className="muted-2 mb">Leave a field empty to use the plan's value. Use -1 for unlimited.</p>
    <div className="grid c2">{LIMITS.map(([k, l]) => <Input key={k} label={l} type="number" min="-1" placeholder={`Plan: ${limitText(org.limits[k] ?? 0)}`} value={lim[k]} onChange={(e) => setLim({ ...lim, [k]: e.target.value })} />)}</div>
    <div className="grid c2">{FEATURES.map(([k, l]) => <Select key={k} label={l} value={feat[k] === null ? '' : String(feat[k])} onChange={(e) => setFeat({ ...feat, [k]: e.target.value === '' ? null : e.target.value === 'true' })}><option value="">Use plan ({org.limits[k] ? 'on' : 'off'})</option><option value="true">Always on</option><option value="false">Always off</option></Select>)}</div>
  </Modal>
}

function DomainsModal({ org, onClose, onSave }) {
  const [text, setText] = useState((org.allowed_domains || []).join(', '))
  const [lock, setLock] = useState(!!org.candidate_domain_lock)
  const list = text.split(/[\s,;]+/).map((d) => d.trim().replace(/^@/, '')).filter(Boolean)
  return <Modal title="Allowed e-mail domains" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={() => onSave({ allowed_domains: list, candidate_domain_lock: list.length ? lock : false })}>Save</Button></>}>
    <Input label="Domains" placeholder="sconexsoft.com, sconexsoft.in" value={text} onChange={(e) => setText(e.target.value)} hint="Comma separated, without @. Subdomains such as mail.sconexsoft.com are accepted too. Leave empty for no restriction." />
    {list.length > 0 && <Check_ label="Also restrict candidates to these domains" checked={lock} onChange={(e) => setLock(e.target.checked)} />}
    <Alert tone="info" className="mt">Existing users are not removed if their address is outside the list; the rule applies when new users are added.</Alert>
  </Modal>
}
