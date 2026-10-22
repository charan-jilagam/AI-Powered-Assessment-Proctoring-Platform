import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ShieldCheck } from 'lucide-react'
import { homeFor, useAuth } from '../../lib/auth'
import { Alert, Button, Input } from '../../ui'

export function AuthShell({ children, headline = 'Run assessments you can stand behind.', blurb = 'Test codes, live monitoring and evidence-backed reviews for every candidate.' }) {
  return (
    <div className="auth">
      <div className="auth-art">
        <Link to="/" className="brand" style={{ padding: 0 }}><span className="mark"><ShieldCheck size={16} /></span>ProctorAI</Link>
        <div><h2>{headline}</h2><p>{blurb}</p></div>
        <small style={{ color: 'var(--ink-mute)' }}>Taking a test? Use the link or code your organizer sent you.</small>
      </div>
      <div className="auth-form"><div className="auth-card">{children}</div></div>
    </div>
  )
}

export default function Login() {
  const { login, status, user, notice } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { if (status === 'ready') nav(homeFor(user), { replace: true }) }, [status, user, nav])

  async function submit(e) {
    e.preventDefault(); setErr(''); setBusy(true)
    try {
      const u = await login(email.trim(), password)
      nav(loc.state?.from && loc.state.from.startsWith(u.role === 'super_admin' ? '/super' : '/app') ? loc.state.from : homeFor(u), { replace: true })
    } catch (e2) { setErr(e2.message); setBusy(false) }
  }
  const message = loc.state?.notice || notice
  return (
    <AuthShell>
      <h1>Sign in</h1>
      <p className="muted mb">For organization admins, reviewers and platform staff.</p>
      {message && <Alert tone="warn">{message}</Alert>}
      {err && <Alert tone="bad">{err}</Alert>}
      <form onSubmit={submit}>
        <Input label="Work email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <Input label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <Button variant="primary" block busy={busy} type="submit" className="lg">Sign in</Button>
      </form>
      <p className="mt" style={{ fontSize: 13.5 }}><Link to="/forgot-password">Forgot your password?</Link></p>
    </AuthShell>
  )
}
