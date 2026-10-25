import { useState } from 'react'
import { KeyRound, UserPlus } from 'lucide-react'
import { api } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { fmtDateTime } from '../../lib/format'
import { useDocumentTitle } from '../../lib/hooks'
import { Alert, Async, Badge, Button, PageHeader, Panel, useLoad, useUI } from '../../ui'
import { AddStaffModal, LinkModal } from '../../ui/staff'

export default function Team() {
  useDocumentTitle('Team')
  const { user: me, org } = useAuth()
  const { error, toast } = useUI()
  const state = useLoad(() => api.get('/org/team'), [])
  const [adding, setAdding] = useState(false)
  const [link, setLink] = useState(null)
  const patch = async (u, body, msg) => { try { await api.patch(`/org/team/${u.id}`, body); toast(msg); state.reload() } catch (e) { error(e) } }
  return (
    <>
      <PageHeader title="Team" subtitle="Admins build tests and manage the organization. Reviewers watch live exams and review results."><Button variant="primary" icon={UserPlus} onClick={() => setAdding(true)}>Add member</Button></PageHeader>
      <Async state={state}>{(rows) => (
        <>
          <Alert tone="info">{rows.length} seat{rows.length === 1 ? '' : 's'} used on the {org.plan_name} plan.{org.allowed_domains?.length ? <> New members must use an e-mail address ending in {org.allowed_domains.map((d) => '@' + d).join(', ')}.</> : null} Each new member receives an invitation and a verification e-mail.</Alert>
          <Panel flush><div className="table-wrap"><table className="t"><thead><tr><th>Member</th><th>Role</th><th>Status</th><th>E-mail</th><th>Last sign-in</th><th /></tr></thead><tbody>
            {rows.map((u) => { const self = u.id === me.id; return (
              <tr key={u.id}><td><b>{u.full_name}</b> {self && <Badge tone="info">You</Badge>}<div className="sub">{u.email}</div></td>
                <td>{self ? <Badge tone="info" status={u.role} /> : <select className="input" style={{ width: 'auto', height: 32 }} aria-label={`Role for ${u.full_name}`} value={u.role} onChange={(e) => patch(u, { role: e.target.value }, 'Role updated')}><option value="admin">Admin</option><option value="reviewer">Reviewer</option></select>}</td>
                <td>{u.is_active ? <Badge status="active" /> : <Badge status="suspended">Disabled</Badge>}</td><td>{u.email_verified ? <Badge tone="ok">Verified</Badge> : <Badge tone="warn">Not verified</Badge>}</td><td className="muted">{u.last_login_at ? fmtDateTime(u.last_login_at) : 'Never'}</td>
                <td className="num nowrap">{!self && <><Button size="sm" icon={KeyRound} onClick={async () => { try { const r = await api.post(`/org/team/${u.id}/reset-link`); setLink({ title: `Reset link for ${u.full_name}`, url: r.reset_url }) } catch (e) { error(e) } }}>Reset link</Button>{' '}<Button size="sm" onClick={() => patch(u, { is_active: !u.is_active }, u.is_active ? 'Member disabled' : 'Member enabled')}>{u.is_active ? 'Disable' : 'Enable'}</Button></>}</td></tr>) })}
          </tbody></table></div></Panel></>
      )}</Async>
      {adding && <AddStaffModal allowTempPassword={false} onClose={() => { setAdding(false); state.reload() }} onSubmit={(b) => api.post('/org/team', { full_name: b.full_name, email: b.email, role: b.role })} />}
      {link && <LinkModal title={link.title} url={link.url} onClose={() => setLink(null)} />}
    </>
  )
}
