import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { BookOpen, Camera, Clock, FileQuestion, Lock, Mic, ScanFace, ShieldCheck } from 'lucide-react'
import { candToken, pub } from '../../lib/api'
import { fmtDateTime } from '../../lib/format'
import { useDocumentTitle } from '../../lib/hooks'
import { Alert, Button, Input, Loading } from '../../ui'
import { CodeEntry } from '../public/Landing'

export function Brand({ org }) {
  return (
    <div className="brandline">
      {org?.logo_url ? <img src={org.logo_url} alt={org.name} onError={(e) => { e.currentTarget.style.display = 'none' }} /> : null}
      <b>{org?.name}</b>
    </div>
  )
}

export default function Join() {
  const { code } = useParams()
  const [params] = useSearchParams()
  const nav = useNavigate()
  const [info, setInfo] = useState(null)
  const [missing, setMissing] = useState('')
  const [f, setF] = useState({ full_name: '', email: '', phone: '', access_password: '', fields: {} })
  const [agree, setAgree] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [step, setStep] = useState('details')   // 'details' -> 'code' when the test verifies e-mail addresses
  const [otp, setOtp] = useState('')
  const [devCode, setDevCode] = useState('')
  const [wait, setWait] = useState(0)
  const [note, setNote] = useState('')
  const timer = useRef(null)
  const invite = params.get('invite') || undefined
  useDocumentTitle(info?.title || 'Join a test')

  useEffect(() => { pub.get(`/public/tests/${encodeURIComponent(code)}`).then(setInfo).catch((e) => setMissing(e.message)) }, [code])
  useEffect(() => () => clearInterval(timer.current), [])
  useEffect(() => {
    if (info?.organization?.brand_color) document.documentElement.style.setProperty('--accent', info.organization.brand_color)
    return () => document.documentElement.style.removeProperty('--accent')
  }, [info])

  if (missing) return (
    <div className="cand-wrap"><div className="cand-card"><h1>That code did not work</h1><Alert tone="bad" className="mt">{missing}</Alert><p className="muted-2 mb">Check the code with whoever invited you. Codes have 8 letters and numbers.</p><CodeEntry autoFocus /></div></div>
  )
  if (!info) return <Loading />

  const p = info.proctoring
  const closed = !info.available
  function cooldown(sec) {
    clearInterval(timer.current); setWait(sec)
    timer.current = setInterval(() => setWait((w) => { if (w <= 1) { clearInterval(timer.current); return 0 } return w - 1 }), 1000)
  }
  async function sendCode() {
    setErr(''); setNote(''); setBusy(true)
    try {
      const r = await pub.post(`/public/tests/${encodeURIComponent(code)}/send-code`, { email: f.email.trim(), full_name: f.full_name.trim() || undefined, invite_token: invite })
      if (r.status === 'not_required') { await join(); return }
      setDevCode(r.dev_code || ''); setOtp(''); setStep('code'); cooldown(45)
      setNote(`We sent a ${6}-digit code to ${f.email.trim()}. It works for ${r.expires_minutes || 10} minutes.`)
      setBusy(false)
    } catch (x) { setErr(x.message); setBusy(false) }
  }
  async function join() {
    setErr(''); setBusy(true)
    try {
      const r = await pub.post(`/public/tests/${encodeURIComponent(code)}/join`, { full_name: f.full_name.trim(), email: f.email.trim(), phone: f.phone || undefined, fields: f.fields, access_password: f.access_password || undefined, invite_token: invite, email_code: step === 'code' ? otp.trim() : undefined })
      candToken.set(r.token)
      nav('/exam', { replace: true })
    } catch (x) { setErr(x.message); setBusy(false) }
  }
  function submit(e) {
    e.preventDefault()
    if (step === 'code') return join()
    return info.requires_email_verification ? sendCode() : join()
  }

  return (
    <div className="cand-wrap">
      <div className="cand-card">
        <Brand org={info.organization} />
        <h1>{info.title}</h1>
        {info.description && <p className="muted-2" style={{ whiteSpace: 'pre-wrap', marginTop: 6 }}>{info.description}</p>}
        <ul className="facts">
          <li><Clock size={16} />{info.duration_minutes} minutes</li>
          <li><FileQuestion size={16} />{info.question_count} question{info.question_count === 1 ? '' : 's'}{info.coding_problem_count ? ` + ${info.coding_problem_count} coding` : ''}</li>
          {p.webcam_required && <li><Camera size={16} />Webcam required</li>}
          {p.microphone_required && <li><Mic size={16} />Microphone required</li>}
          {p.ai_monitoring && <li><ScanFace size={16} />Face monitoring</li>}
          {p.fullscreen_required && <li><ShieldCheck size={16} />Fullscreen exam</li>}
        </ul>
        {info.window.start && info.window.state === 'not_started' && <Alert tone="warn">This test opens on {fmtDateTime(info.window.start)}.</Alert>}
        {closed && info.window.state !== 'not_started' && <Alert tone="bad">{info.unavailable_reason || 'This test is not available.'}</Alert>}
        {!closed && (
          <form onSubmit={submit} className="mt">
            {err && <Alert tone="bad">{err}</Alert>}
            {step === 'code' ? (
              <>
                {note && <Alert tone="info">{note}</Alert>}
                {devCode && <Alert tone="warn">Development mode: no e-mail service is set up, so your code is <b>{devCode}</b>.</Alert>}
                <Input label="6-digit code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required autoFocus value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))} hint="Check your spam folder if it does not arrive." />
                <label className="check mb"><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} required /><span>I will take this test myself, without help, and I understand my screen activity{p.webcam_required ? ' and webcam' : ''} will be monitored.</span></label>
                <Button type="submit" variant="primary" size="lg" block busy={busy} disabled={!agree || otp.length !== 6}>Verify and continue</Button>
                <div className="row" style={{ justifyContent: 'space-between', marginTop: 12 }}>
                  <button type="button" className="btn ghost sm" onClick={() => { setStep('details'); setErr(''); setNote('') }}>Change e-mail</button>
                  <button type="button" className="btn ghost sm" disabled={wait > 0 || busy} onClick={sendCode}>{wait > 0 ? `Resend in ${wait}s` : 'Resend code'}</button>
                </div>
              </>
            ) : (<>
            <Input label="Full name" required autoComplete="name" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} hint="As on your ID. It appears on your result." />
            <Input label="E-mail" type="email" required autoComplete="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} hint={invite ? 'Use the address your invitation was sent to.' : info.email_domains?.length ? `Use your ${info.email_domains.map((d) => '@' + d).join(' / ')} address. We e-mail a code to it.` : info.requires_email_verification ? 'We will e-mail a 6-digit code to this address. Use it again to resume if your connection drops.' : 'Use the same e-mail to resume if your connection drops.'} />
            {info.candidate_fields.map((c) => <Input key={c.key} label={c.label} required={c.required} value={f.fields[c.key] || ''} onChange={(e) => setF({ ...f, fields: { ...f.fields, [c.key]: e.target.value } })} />)}
            {info.requires_password && <Input label="Access password" type="password" required autoComplete="off" value={f.access_password} onChange={(e) => setF({ ...f, access_password: e.target.value })} icon={Lock} hint="Given to you separately by the organizer." />}
            <label className="check mb"><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} required /><span>I will take this test myself, without help, and I understand my screen activity{p.webcam_required ? ' and webcam' : ''} will be monitored.</span></label>
            <Button type="submit" variant="primary" size="lg" block busy={busy} disabled={!agree}>{info.requires_email_verification ? 'Send verification code' : 'Continue'}</Button>
            </>)}
          </form>
        )}
        <p className="muted mt" style={{ fontSize: 13 }}><Link to="/">Use a different code</Link> · <Link to="/guide/candidate" target="_blank"><BookOpen size={12} style={{ verticalAlign: '-1px' }} /> Candidate guide</Link></p>
      </div>
    </div>
  )
}
