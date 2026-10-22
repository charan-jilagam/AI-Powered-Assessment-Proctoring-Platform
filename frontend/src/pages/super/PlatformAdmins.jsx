import { useState } from 'react'
import { Plus } from 'lucide-react'
import { api } from '../../lib/api'
import { fmtDateTime } from '../../lib/format'
import { useAuth } from '../../lib/auth'
import { useDocumentTitle } from '../../lib/hooks'
import { Alert, Async, Badge, Button, CopyButton, Input, Modal, PageHeader, Panel, useLoad, useUI } from '../../ui'

export default function PlatformAdmins() {
  useDocumentTitle('Platform admins')
  const { user: me } = useAuth()
  const { error } = useUI()
  const state = useLoad(() => api.get('/superadmin/platform-admins'), [])
  const [adding, setAdding] = useState(false)
  return (
    <>
      <PageHeader title="Platform admins" subtitle="People with full control of the platform and every organization."><Button variant="primary" icon={Plus} onClick={() => setAdding(true)}>Add platform admin</Button></PageHeader>
      <Async state={state}>{(rows) => (
        <Panel flush><table className="t"><thead><tr><th>Name</th><th>Status</th><th>Last sign-in</th><th /></tr></thead><tbody>
          {rows.map((u) => <tr key={u.id}><td><b>{u.full_name}</b> {u.id === me.id && <Badge tone="info">You</Badge>}<div className="sub">{u.email}</div></td><td>{u.is_active ? <Badge status="active" /> : <Badge status="suspended">Disabled</Badge>}</td><td className="muted">{fmtDateTime(u.last_login_at)}</td>
            <td className="num">{u.id !== me.id && <Button size="sm" onClick={async () => { try { await api.patch(`/superadmin/platform-admins/${u.id}`, { is_active: !u.is_active }); state.reload() } catch (e) { error(e) } }}>{u.is_active ? 'Disable' : 'Enable'}</Button>}</td></tr>)}
        </tbody></table></Panel>
      )}</Async>
      {adding && <Add onClose={() => { setAdding(false); state.reload() }} />}
    </>
  )
}

function Add({ onClose }) {
  const { error } = useUI()
  const [f, setF] = useState({ full_name: '', email: '', temp_password: '' })
  const [made, setMade] = useState(null)
  const [busy, setBusy] = useState(false)
  async function go(e) { e?.preventDefault(); setBusy(true); const b = { ...f }; if (!b.temp_password) delete b.temp_password; try { setMade(await api.post('/superadmin/platform-admins', b)) } catch (x) { error(x) } finally { setBusy(false) } }
  if (made) return <Modal title="Platform admin added" onClose={onClose} footer={<Button variant="primary" onClick={onClose}>Done</Button>}>
    <Alert tone="ok">{made.full_name} now has full platform access.</Alert>{made.invite_url && <div className="row"><input className="input mono grow" readOnly value={made.invite_url} aria-label="Activation link" /><CopyButton text={made.invite_url} /></div>}</Modal>
  return <Modal title="Add platform admin" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} onClick={go}>Add</Button></>}>
    <Alert tone="warn">Platform admins can see and change every organization. Add only people you trust with that.</Alert>
    <form onSubmit={go}><Input label="Full name" required value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /><Input label="E-mail" type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /><Input label="Temporary password (optional)" autoComplete="off" value={f.temp_password} onChange={(e) => setF({ ...f, temp_password: e.target.value })} /></form></Modal>
}
