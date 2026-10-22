import { useState } from 'react'
import { Alert, Button, CopyButton, Input, Modal, Select, useUI } from './index'

// Shared by the super-admin org page and the client Team page. `onSubmit(body)` returns the created user.
export function AddStaffModal({ onSubmit, onClose, allowAdminRole = true, allowTempPassword = true, title = 'Add a team member' }) {
  const { error } = useUI()
  const [f, setF] = useState({ full_name: '', email: '', role: allowAdminRole ? 'admin' : 'reviewer', temp_password: '' })
  const [busy, setBusy] = useState(false)
  const [made, setMade] = useState(null)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  async function go(e) {
    e?.preventDefault(); setBusy(true)
    const body = { ...f }; if (!body.temp_password) delete body.temp_password
    try { setMade(await onSubmit(body)) } catch (x) { error(x) } finally { setBusy(false) }
  }
  if (made) return (
    <Modal title="Team member added" onClose={onClose} footer={<Button variant="primary" onClick={onClose}>Done</Button>}>
      <Alert tone="ok"><b>{made.full_name}</b> can now activate their {made.role} account.</Alert>
      {made.invite_url && <><p className="muted-2 mb">Share this one-time link if the e-mail does not arrive:</p>
        <div className="row"><input className="input mono grow" readOnly value={made.invite_url} onFocus={(e) => e.target.select()} aria-label="Activation link" /><CopyButton text={made.invite_url} /></div></>}
    </Modal>
  )
  return (
    <Modal title={title} onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} onClick={go}>Add and invite</Button></>}>
      <form onSubmit={go}>
        <Input label="Full name" required value={f.full_name} onChange={set('full_name')} />
        <Input label="E-mail" type="email" required value={f.email} onChange={set('email')} />
        <Select label="Role" value={f.role} onChange={set('role')} hint={f.role === 'admin' ? 'Admins create tests, manage the team and see the answer key.' : 'Reviewers monitor live exams and review results. They cannot edit tests or see answers.'}>
          {allowAdminRole && <option value="admin">Admin</option>}<option value="reviewer">Reviewer</option>
        </Select>
        {allowTempPassword && <Input label="Temporary password (optional)" autoComplete="off" value={f.temp_password} onChange={set('temp_password')} hint="Leave empty to send an activation link." />}
      </form>
    </Modal>
  )
}

export function LinkModal({ title, url, onClose }) {
  return (
    <Modal title={title} onClose={onClose} footer={<Button variant="primary" onClick={onClose}>Done</Button>}>
      <p className="muted-2 mb">The link was also e-mailed. It works once and expires in a few hours.</p>
      <div className="row"><input className="input mono grow" readOnly value={url} onFocus={(e) => e.target.select()} aria-label="Link" /><CopyButton text={url} /></div>
    </Modal>
  )
}
