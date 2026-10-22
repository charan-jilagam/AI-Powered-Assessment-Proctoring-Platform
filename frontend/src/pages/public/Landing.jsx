import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Camera, Code2, KeyRound, ShieldCheck, Webhook, Eye, Lock, Check } from 'lucide-react'
import { pub } from '../../lib/api'
import { money, limitText } from '../../lib/format'
import { Alert, Button, Input, Textarea } from '../../ui'

export function CodeEntry({ autoFocus }) {
  const nav = useNavigate()
  const [cells, setCells] = useState(Array(8).fill(''))
  const refs = [] // eslint-disable-line
  const set = (arr) => { setCells(arr) }
  const focus = (i) => document.getElementById(`code-${Math.max(0, Math.min(7, i))}`)?.focus()
  function onChange(i, v) {
    const clean = v.toUpperCase().replace(/[^A-Z0-9]/g, '')
    if (!clean) { const n = [...cells]; n[i] = ''; set(n); return }
    const n = [...cells]
    clean.split('').slice(0, 8 - i).forEach((c, k) => { n[i + k] = c })
    set(n); focus(i + clean.length)
  }
  function onKey(i, e) {
    if (e.key === 'Backspace' && !cells[i]) { focus(i - 1) }
    if (e.key === 'ArrowLeft') focus(i - 1)
    if (e.key === 'ArrowRight') focus(i + 1)
    if (e.key === 'Enter' && cells.every(Boolean)) go()
  }
  const code = cells.join('')
  const go = () => code.length === 8 && nav(`/t/${code}`)
  return (
    <div>
      <div className="code-cells" role="group" aria-label="Test code, 8 characters">
        {cells.map((c, i) => (
          <span key={i} style={{ display: 'contents' }}>
            {i === 4 && <span className="code-dash" aria-hidden>–</span>}
            <input id={`code-${i}`} className="code-cell" value={c} inputMode="text" autoCapitalize="characters" autoComplete="off" spellCheck={false} autoFocus={autoFocus && i === 0}
              aria-label={`Character ${i + 1}`} onChange={(e) => onChange(i, e.target.value)} onKeyDown={(e) => onKey(i, e)} onPaste={(e) => { e.preventDefault(); onChange(i, e.clipboardData.getData('text')) }} onFocus={(e) => e.target.select()} />
          </span>
        ))}
      </div>
      <Button variant="primary" size="lg" disabled={code.length !== 8} onClick={go} className="mt">Open my test</Button>
    </div>
  )
}

const FEATURES = [
  { icon: KeyRound, t: 'One code per test', d: 'Publish a test and share its 8-character code or link. Candidates join in seconds — no accounts, no installs.' },
  { icon: Camera, t: 'Proctoring that explains itself', d: 'Tab switches, fullscreen exits, copy-paste, camera loss and AI face checks are logged with snapshot evidence and a risk score.' },
  { icon: Eye, t: 'Watch live, review later', d: 'See who is online, message a candidate, add time, or end an attempt. Afterwards, clear or flag each attempt with notes.' },
  { icon: Code2, t: 'Questions of every kind', d: 'Single, multiple, true/false and short answer with negative marking, sections, a reusable bank and CSV import — plus coding problems.' },
  { icon: Lock, t: 'Built for many clients', d: 'Each organization is fully isolated, with its own team, branding, limits, API keys and audit trail.' },
  { icon: Webhook, t: 'Fits your stack', d: 'Signed webhooks and API keys send results to your ATS or LMS. Export every result as CSV.' },
]

export default function Landing() {
  const [plans, setPlans] = useState([])
  const [form, setForm] = useState({ name: '', email: '', company: '', message: '' })
  const [sent, setSent] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { pub.get('/public/plans').then(setPlans).catch(() => {}) }, [])
  const f = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  async function demo(e) {
    e.preventDefault(); setBusy(true); setErr('')
    try { await pub.post('/public/demo-request', form); setSent(true) } catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  return (
    <div className="landing">
      <header className="l-nav">
        <span className="brand"><span className="mark"><ShieldCheck size={16} /></span>ProctorAI</span>
        <nav><a href="#features">Features</a><a href="#pricing">Pricing</a><a href="#demo">Book a demo</a><Link className="btn sm" to="/login">Sign in</Link></nav>
      </header>

      <section className="l-hero">
        <div>
          <h1>Share a code. Run the exam. Trust the result.</h1>
          <p>Create a test, hand candidates an 8-character code, and get scored, proctored results with the evidence to back every decision.</p>
          <div className="row wrap mt"><a className="btn primary lg" href="#demo">Book a demo</a><Link className="btn lg" to="/login">Sign in</Link></div>
        </div>
        <div className="l-entry">
          <h2>Taking a test?</h2>
          <p className="muted-2" style={{ margin: '4px 0 18px' }}>Type the code your organizer gave you.</p>
          <CodeEntry />
        </div>
      </section>

      <section id="features" className="l-section">
        <h2>Everything an exam day needs</h2>
        <div className="l-features">{FEATURES.map((x) => <div key={x.t}><x.icon size={20} /><h3>{x.t}</h3><p>{x.d}</p></div>)}</div>
      </section>

      <section id="pricing" className="l-section">
        <h2>Plans</h2>
        <p className="muted-2" style={{ marginTop: 6 }}>Start with a {plans.length ? 'free trial' : 'trial'}; your account manager sets up the plan that fits.</p>
        <div className="l-plans">
          {plans.map((p) => (
            <div className="l-plan" key={p.id}>
              <h3>{p.name}</h3>
              <div className="price">{p.price_monthly ? money(p.price_monthly, p.currency) : 'Custom'}<small>{p.price_monthly ? ' / month' : ''}</small></div>
              <p className="muted-2" style={{ minHeight: 42 }}>{p.description}</p>
              <ul>
                <li><Check size={14} />{limitText(p.max_candidates_per_month)} candidates / month</li>
                <li><Check size={14} />{limitText(p.max_active_tests)} active tests</li>
                <li><Check size={14} />{limitText(p.max_admins)} team seats</li>
                {p.ai_proctoring && <li><Check size={14} />AI proctoring</li>}
                {p.coding_enabled && <li><Check size={14} />Coding questions</li>}
                {p.api_access && <li><Check size={14} />API & webhooks</li>}
                <li><Check size={14} />{p.evidence_retention_days}-day evidence retention</li>
              </ul>
            </div>
          ))}
        </div>
      </section>

      <section id="demo" className="l-section l-demo">
        <div><h2>See it with your own test</h2><p className="muted-2" style={{ marginTop: 8 }}>Tell us a little about your assessments. We will set up a trial organization and walk you through it.</p></div>
        {sent ? <Alert tone="ok">Thanks — we received your request and will reply by e-mail.</Alert> : (
          <form onSubmit={demo}>
            {err && <Alert tone="bad">{err}</Alert>}
            <div className="grid c2"><Input label="Your name" required value={form.name} onChange={f('name')} /><Input label="Work email" type="email" required value={form.email} onChange={f('email')} /></div>
            <Input label="Company" value={form.company} onChange={f('company')} />
            <Textarea label="What do you want to assess?" value={form.message} onChange={f('message')} />
            <Button variant="primary" type="submit" busy={busy}>Request a demo</Button>
          </form>
        )}
      </section>
      <footer className="l-foot"><span>© {new Date().getFullYear()} ProctorAI</span><Link to="/login">Sign in</Link></footer>
    </div>
  )
}
