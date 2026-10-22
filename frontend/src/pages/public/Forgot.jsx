import { useState } from 'react'
import { Link } from 'react-router-dom'
import { pub } from '../../lib/api'
import { Alert, Button, Input } from '../../ui'
import { AuthShell } from './Login'

export default function Forgot() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(e) {
    e.preventDefault(); setBusy(true); setErr('')
    try { await pub.post('/auth/forgot-password', { email: email.trim() }); setSent(true) } catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  return (
    <AuthShell headline="Locked out? It happens." blurb="We will e-mail a link that lets you choose a new password.">
      <h1>Reset your password</h1>
      {sent ? <Alert tone="ok" className="mt">If an account exists for <b>{email}</b>, a reset link is on its way. It works for 2 hours.</Alert> : (
        <form onSubmit={submit} className="mt">
          {err && <Alert tone="bad">{err}</Alert>}
          <Input label="Work email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <Button variant="primary" block busy={busy} type="submit">Send reset link</Button>
        </form>
      )}
      <p className="mt" style={{ fontSize: 13.5 }}><Link to="/login">Back to sign in</Link></p>
    </AuthShell>
  )
}
