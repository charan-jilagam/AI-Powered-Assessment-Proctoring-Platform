import { useState } from 'react'
import { api } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { Alert, Badge, Button, Input, PageHeader, Panel, useUI } from '../../ui'

export default function Account() {
  const { user, org, refresh, logoutEverywhere } = useAuth()
  const { toast, error, confirm } = useUI()
  const [cur, setCur] = useState('')
  const [pw, setPw] = useState('')
  const [busy, setBusy] = useState(false)
  async function change(e) {
    e.preventDefault(); setBusy(true)
    try { await api.post('/auth/change-password', { current_password: cur, new_password: pw }); toast('Password changed'); setCur(''); setPw(''); refresh() }
    catch (x) { error(x) } finally { setBusy(false) }
  }
  return (
    <>
      <PageHeader title="Your account" />
      <div className="grid c2" style={{ alignItems: 'start' }}>
        <Panel title="Profile">
          <dl className="kv"><dt>Name</dt><dd>{user.full_name}</dd><dt>E-mail</dt><dd>{user.email} {user.role !== 'super_admin' && (user.email_verified ? <Badge tone="ok">Verified</Badge> : <Badge tone="warn">Not verified</Badge>)}</dd><dt>Role</dt><dd><Badge status={user.role} tone="info" /></dd>{org && <><dt>Organization</dt><dd>{org.name}</dd></>}</dl>
        </Panel>
        <Panel title="Change password">
          <form onSubmit={change}>
            {user.must_change_password && <Alert tone="warn">Replace your temporary password to secure the account.</Alert>}
            <Input label="Current password" type="password" autoComplete="current-password" required value={cur} onChange={(e) => setCur(e.target.value)} />
            <Input label="New password" type="password" autoComplete="new-password" required value={pw} onChange={(e) => setPw(e.target.value)} hint="10+ characters with a letter and a number." />
            <Button variant="primary" type="submit" busy={busy}>Change password</Button>
          </form>
        </Panel>
      </div>
      <Panel title="Sessions" className="mt">
        <div className="row between wrap"><p className="muted-2">Signed in somewhere you no longer trust? This signs out every browser and device.</p>
          <Button variant="danger" onClick={async () => { if (await confirm({ title: 'Sign out everywhere', message: 'All your active sessions will end, including this one.', confirmLabel: 'Sign out everywhere', danger: true })) logoutEverywhere().catch(error) }}>Sign out everywhere</Button></div>
      </Panel>
    </>
  )
}
