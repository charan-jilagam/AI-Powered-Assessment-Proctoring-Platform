import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { pub } from '../../lib/api'
import { Alert, Button, Input, Loading } from '../../ui'
import { AuthShell } from './Login'

const rules = (p) => [
  ['At least 10 characters', p.length >= 10],
  ['Contains a letter', /[A-Za-z]/.test(p)],
  ['Contains a number', /\d/.test(p)],
]

export default function SetPassword({ mode }) {
  const [params] = useSearchParams()
  const token = params.get('token') || ''
  const nav = useNavigate()
  const [info, setInfo] = useState(null)
  const [bad, setBad] = useState('')
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const invite = mode === 'invite'

  useEffect(() => {
    if (!token) { setBad('This link is missing its token. Open the link from your e-mail again.'); return }
    pub.get('/auth/token-info', { token }).then(setInfo).catch((e) => setBad(e.message))
  }, [token])

  const ok = rules(pw).every(([, v]) => v) && pw === pw2
  async function submit(e) {
    e.preventDefault(); setBusy(true); setErr('')
    try { await pub.post('/auth/reset-password', { token, new_password: pw }); nav('/signin', { replace: true, state: { notice: 'Password saved. Sign in with your new password.' } }) }
    catch (x) { setErr(x.message); setBusy(false) }
  }
  return (
    <AuthShell headline={invite ? 'Welcome aboard.' : 'Choose a new password.'} blurb={invite ? 'Set a password to activate your account.' : 'You will be signed out everywhere else.'}>
      {!info && !bad && <Loading />}
      {bad && <><h1>Link not valid</h1><Alert tone="bad" className="mt">{bad}</Alert><p><Link to="/forgot-password">Request a new link</Link></p></>}
      {info && (
        <form onSubmit={submit}>
          <h1>{invite ? `Join ${info.organization}` : 'Set a new password'}</h1>
          <p className="muted mb">Account: <b>{info.email}</b></p>
          {err && <Alert tone="bad">{err}</Alert>}
          <Input label="New password" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} required />
          <Input label="Repeat password" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} required error={pw2 && pw !== pw2 ? 'Passwords do not match' : ''} />
          <ul className="hint" style={{ paddingLeft: 18, margin: '0 0 16px' }}>{rules(pw).map(([t, v]) => <li key={t} style={{ color: v ? 'var(--ok)' : undefined }}>{t}</li>)}</ul>
          <Button variant="primary" block busy={busy} disabled={!ok} type="submit">{invite ? 'Activate account' : 'Save password'}</Button>
        </form>
      )}
    </AuthShell>
  )
}
