import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { CheckCircle2 } from 'lucide-react'
import { pub } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { Alert, Loading } from '../../ui'
import { AuthShell } from './Login'

// Opened from the link in the "Verify your e-mail address" message.
export default function VerifyEmail() {
  const [params] = useSearchParams()
  const token = params.get('token') || ''
  const { status, user, refresh } = useAuth()
  const [state, setState] = useState(token ? 'working' : 'missing')
  const [email, setEmail] = useState('')
  const [err, setErr] = useState('')
  const sent = useRef(false)

  useEffect(() => {
    if (!token || sent.current) return
    sent.current = true       // the link works once; React strict mode must not spend it twice
    pub.post('/auth/verify-email', { token })
      .then((r) => { setEmail(r.email || ''); setState('ok'); if (status === 'ready') refresh() })
      .catch((e) => { setErr(e.message); setState('bad') })
  }, []) // eslint-disable-line

  const signedIn = status === 'ready' && user
  return (
    <AuthShell headline="One quick check." blurb="Confirming your address keeps accounts safe and makes sure you receive test results and alerts.">
      {state === 'working' && <Loading />}
      {state === 'missing' && <><h1>Link incomplete</h1><Alert tone="bad" className="mt">This link is missing its token. Open the link from your e-mail again.</Alert></>}
      {state === 'bad' && <><h1>Link not valid</h1><Alert tone="bad" className="mt">{err || 'This link is invalid or has expired.'}</Alert><p className="muted-2">Sign in and press <b>Resend verification e-mail</b> in the yellow banner to get a fresh link.</p><Link className="btn primary" to="/signin">Sign in</Link></>}
      {state === 'ok' && (
        <>
          <h1><CheckCircle2 size={26} style={{ verticalAlign: '-4px', color: 'var(--ok)' }} /> E-mail verified</h1>
          <p className="muted-2 mt">{email ? <><b>{email}</b> is confirmed.</> : 'Your address is confirmed.'} You can now create tests.</p>
          <Link className="btn primary mt" to={signedIn ? (user.role === 'super_admin' ? '/super' : '/app') : '/signin'}>{signedIn ? 'Go to my dashboard' : 'Sign in'}</Link>
        </>
      )}
    </AuthShell>
  )
}
