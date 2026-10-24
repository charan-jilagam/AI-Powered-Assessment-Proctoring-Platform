import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bell, ChevronLeft, ChevronRight, Flag, Maximize, Send, WifiOff } from 'lucide-react'
import { ApiError, cand, candToken, setCandidateExpiredHandler } from '../../lib/api'
import { clock } from '../../lib/format'
import { Alert, Button, Loading, Modal } from '../../ui'
import { ThemeToggle } from '../../lib/theme'
import { CamTile, ProctorAlerts } from './ProctorHud'
import { CodeEntry } from '../public/Landing'
import CodingPanel from './CodingPanel'
import Finished from './Finished'
import Lobby from './Lobby'
import { useMedia, watchVoice } from './useMedia'

const FINAL = new Set(['submitted', 'terminated'])

export default function ExamRoom() {
  const [state, setState] = useState(null)
  const [problem, setProblem] = useState('')   // 'none' | 'ended' | message
  const media = useMedia()

  const load = useCallback(async () => {
    if (!candToken.get()) { setProblem('none'); return }
    try { setState(await cand.get('/attempt')) } catch (e) { if (e.status !== 401) setProblem(e.message) }
  }, [])
  useEffect(() => { load() }, [load])
  useEffect(() => { setCandidateExpiredHandler(() => setProblem('ended')) }, [])
  useEffect(() => {
    if (state?.test?.organization?.brand_color) document.documentElement.style.setProperty('--accent', state.test.organization.brand_color)
    document.title = state?.test?.title ? `${state.test.title} · ORVEXA` : 'Test · ORVEXA'
    return () => document.documentElement.style.removeProperty('--accent')
  }, [state?.test?.title, state?.test?.organization?.brand_color]) // eslint-disable-line

  const finalStatus = state ? FINAL.has(state.attempt.status) : false
  const stopMedia = media.stop
  useEffect(() => {
    if (!finalStatus) return
    stopMedia()
    if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {})
  }, [finalStatus, stopMedia])

  if (problem === 'none' || problem === 'ended') return (
    <div className="cand-wrap"><div className="cand-card">
      <h1>{problem === 'ended' ? 'This session has ended' : 'Enter your test code'}</h1>
      <p className="muted-2 mb">{problem === 'ended' ? 'Your session was replaced (you may have opened the test in another window or device) or it expired. Enter the code again with the same e-mail to continue where you left off.' : 'Use the code your organizer sent you.'}</p>
      <CodeEntry autoFocus />
    </div></div>
  )
  if (problem) return <div className="cand-wrap"><div className="cand-card"><Alert tone="bad">{problem}</Alert><Button onClick={() => { setProblem(''); load() }}>Try again</Button></div></div>
  if (!state) return <Loading />

  const status = state.attempt.status
  if (FINAL.has(status)) return <Finished state={state} />
  if (status === 'registered') return <Lobby state={state} media={media} onStarted={(s) => setState(s)} />
  if (status === 'in_progress') return <Exam key={state.attempt.id} state={state} media={media} onDone={load} />
  return <div className="cand-wrap"><div className="cand-card"><Alert tone="bad">This attempt is no longer available.</Alert><Link to="/">Back to start</Link></div></div>
}

/* ------------------------------------------------------------------ */
function Exam({ state, media, onDone }) {
  const cfg = state.test.proctoring_config
  const questions = state.questions || []
  const problems = state.coding_problems || []
  const attemptId = state.attempt.id
  const backupKey = `pai_ans_${attemptId}`

  const [answers, setAnswers] = useState(() => { let local = {}; try { local = JSON.parse(sessionStorage.getItem(backupKey)) || {} } catch { /* none */ } return { ...local, ...(state.answers || {}) } })
  const [flagged, setFlagged] = useState(state.flagged || [])
  const [idx, setIdx] = useState(0)
  const [view, setView] = useState(questions.length ? 'questions' : 'coding')
  const [save, setSave] = useState('saved')           // saved | saving | offline
  const [notices, setNotices] = useState((state.messages || []).map((m) => ({ id: 'm' + m.id, text: m.body, tone: 'info' })))
  const [alerts, setAlerts] = useState([])
  const [confirm, setConfirm] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [fsLost, setFsLost] = useState(false)
  const [ready, setReady] = useState(false)              // user gesture gate (camera / fullscreen) after a refresh
  const [hint, setHint] = useState('')
  const [gateErr, setGateErr] = useState('')

  const clockRef = useRef({ remaining: state.attempt.remaining_seconds, at: performance.now() })
  const [left, setLeft] = useState(state.attempt.remaining_seconds)
  const stateRef = useRef({ answers, flagged }); stateRef.current = { answers, flagged }
  const lastMsg = useRef(Math.max(0, ...(state.messages || []).map((m) => m.id)))
  const finishing = useRef(false)
  const lastReport = useRef({})
  const video = useRef(null)
  const dirty = useRef(false)
  const alertSeq = useRef(0)
  const pushAlert = useCallback((o, auto) => setAlerts((a) => [...a.filter((x) => !(x.code === o.code && x.severity < 2)), { id: ++alertSeq.current, code: o.code, label: o.label, severity: o.severity, n: o.level2_count, max: o.max_level2, auto }]), [])
  const dismissAlert = useCallback((id) => setAlerts((a) => a.filter((x) => x.id !== id)), [])
  useEffect(() => { document.body.classList.add('in-exam'); return () => document.body.classList.remove('in-exam') }, [])

  const needCam = cfg.webcam_required
  const needGate = (needCam && !media.cam) || (cfg.fullscreen_required && !document.fullscreenElement)

  /* ---------- timer ---------- */
  useEffect(() => {
    const id = setInterval(() => {
      const rem = clockRef.current.remaining - (performance.now() - clockRef.current.at) / 1000
      setLeft(Math.max(0, rem))
      if (rem <= 0 && !finishing.current) submit(true)
    }, 500)
    return () => clearInterval(id)
  }, []) // eslint-disable-line

  /* ---------- finish ---------- */
  const submit = useCallback(async (auto = false) => {
    if (finishing.current) return
    finishing.current = true; setSubmitting(true)
    try { await cand.post('/attempt/submit', { answers: stateRef.current.answers, flagged: stateRef.current.flagged }); try { sessionStorage.removeItem(backupKey) } catch { /* ignore */ } await onDone() }
    catch (e) {
      finishing.current = false; setSubmitting(false)
      if (e.status === 409) await onDone()
      else if (!auto) setNotices((n) => [...n, { id: Date.now(), text: `Could not submit: ${e.message} Your answers are kept; try again.`, tone: 'bad' }])
      else setTimeout(() => submit(true), 3000)
    }
  }, [onDone, backupKey])

  /* ---------- autosave ---------- */
  useEffect(() => {
    dirty.current = true
    try { sessionStorage.setItem(backupKey, JSON.stringify(answers)) } catch { /* ignore */ }
    setSave('saving')
    const t = setTimeout(flush, 700)
    return () => clearTimeout(t)
  }, [answers, flagged]) // eslint-disable-line
  async function flush() {
    if (finishing.current) return
    try {
      const r = await cand.put('/attempt/answers', { answers: stateRef.current.answers, flagged: stateRef.current.flagged })
      dirty.current = false; setSave('saved')
      if (r.remaining_seconds != null) clockRef.current = { remaining: r.remaining_seconds, at: performance.now() }
    } catch (e) { if (e instanceof ApiError && e.status === 409) onDone(); else setSave('offline') }
  }
  useEffect(() => { const id = setInterval(() => { if (dirty.current) flush() }, 5000); return () => clearInterval(id) }, []) // eslint-disable-line

  /* ---------- reporting ---------- */
  const report = useCallback(async (code, details, withImage = true) => {
    if (finishing.current) return
    const now = Date.now()
    if (now - (lastReport.current[code] || 0) < 3000) return   // the server also de-duplicates; this just saves requests
    lastReport.current[code] = now
    const image = withImage && media.cam && video.current ? media.capture(video.current, 320, 0.55) : undefined
    try {
      const o = await cand.post('/attempt/violations', { code, details, image })
      if (o.terminated) { finishing.current = true; await onDone(); return }
      if (o.recorded) pushAlert(o, cfg.auto_terminate)
    } catch { /* offline: the heartbeat will keep trying; a missed flag is not the candidate's fault */ }
  }, [media, cfg.auto_terminate, onDone, pushAlert])

  /* ---------- heartbeat ---------- */
  useEffect(() => {
    const beat = async () => {
      if (finishing.current) return
      try {
        const h = await cand.post(`/attempt/heartbeat?after=${lastMsg.current}`, { visible: document.visibilityState === 'visible', fullscreen: !!document.fullscreenElement, camera: needCam ? media.cam : null, mic: cfg.microphone_required ? media.mic : null })
        if (h.status !== 'in_progress') { finishing.current = true; await onDone(); return }
        clockRef.current = { remaining: h.remaining_seconds, at: performance.now() }
        if (h.messages?.length) { lastMsg.current = h.messages[h.messages.length - 1].id; setNotices((n) => [...n, ...h.messages.map((m) => ({ id: 'm' + m.id, text: m.body, tone: 'info' }))]) }
        if (save === 'offline') flush()
      } catch { /* flush handles the offline banner */ }
    }
    const id = setInterval(beat, 10000); beat()
    return () => clearInterval(id)
  }, [media.cam, media.mic]) // eslint-disable-line

  /* ---------- browser lockdown ---------- */
  useEffect(() => {
    if (!ready) return
    const on = (t, e, h, o) => { t.addEventListener(e, h, o); return () => t.removeEventListener(e, h, o) }
    const off = []
    if (cfg.detect_tab_switch) {
      off.push(on(document, 'visibilitychange', () => { if (document.visibilityState === 'hidden') report('TAB_SWITCH', 'Left the exam tab', false) }))
      off.push(on(window, 'blur', () => setTimeout(() => { if (document.visibilityState === 'visible' && !document.hasFocus()) report('WINDOW_BLUR', 'Exam window lost focus', false) }, 600)))
    }
    if (cfg.fullscreen_required) off.push(on(document, 'fullscreenchange', () => { if (!document.fullscreenElement) { setFsLost(true); report('FULLSCREEN_EXIT', 'Exited fullscreen') } else setFsLost(false) }))
    if (cfg.block_copy_paste) {
      for (const ev of ['copy', 'cut', 'paste']) off.push(on(document, ev, (e) => { e.preventDefault(); report('COPY_PASTE', `Tried to ${ev}`, false) }))
      off.push(on(document, 'contextmenu', (e) => { e.preventDefault(); report('RIGHT_CLICK', 'Right-click', false) }))
      off.push(on(document, 'keydown', (e) => {
        const k = e.key.toLowerCase(), mod = e.ctrlKey || e.metaKey
        if (k === 'f12' || (mod && e.shiftKey && ['i', 'j', 'c'].includes(k)) || (mod && ['u', 's', 'p'].includes(k)) || k === 'printscreen') { e.preventDefault(); report('SHORTCUT', `Blocked shortcut ${mod ? 'Ctrl+' : ''}${e.key}`, false) }
      }))
    }
    let rs; off.push(on(window, 'resize', () => { clearTimeout(rs); rs = setTimeout(() => { if (!document.fullscreenElement && cfg.fullscreen_required) return; report('SCREEN_RESIZE', `Window resized to ${innerWidth}x${innerHeight}`, false) }, 1200) }))
    off.push(on(window, 'beforeunload', (e) => { if (!finishing.current) { e.preventDefault(); e.returnValue = '' } }))
    return () => off.forEach((f) => f())
  }, [ready, cfg, report])

  /* ---------- camera, microphone, snapshots, AI ---------- */
  useEffect(() => { if (media.cam) media.attach(video.current) }, [media.cam, ready]) // eslint-disable-line
  useEffect(() => { if (ready && needCam && !media.cam) report('CAMERA_LOST', 'Camera stopped', false) }, [media.cam]) // eslint-disable-line
  useEffect(() => {
    if (!ready || !cfg.microphone_required || !media.mic || !media.streamRef.current) return
    return watchVoice(media.streamRef.current, () => report('AUDIO_VOICE', 'Sustained sound detected', false))
  }, [ready, media.mic]) // eslint-disable-line
  useEffect(() => {
    if (!ready || !media.cam || !cfg.snapshot_interval_seconds) return
    const id = setInterval(() => { const img = media.capture(video.current, 320, 0.5); if (img) cand.post('/attempt/snapshot', { image: img }).catch(() => {}) }, cfg.snapshot_interval_seconds * 1000)
    return () => clearInterval(id)
  }, [ready, media.cam, cfg.snapshot_interval_seconds]) // eslint-disable-line
  useEffect(() => {
    if (!ready || !media.cam || !cfg.ai_monitoring) return
    let busy = false
    const id = setInterval(async () => {
      if (busy || finishing.current) return
      const img = media.capture(video.current, 320, 0.5); if (!img) return
      busy = true
      try {
        const r = await cand.post('/attempt/analyze', { image: img })
        if (r.terminated) { finishing.current = true; onDone(); return }
        const live = r.findings || []
        setHint(r.available && live.length ? live[0].label : '')
        if (r.outcome?.recorded) pushAlert(r.outcome, cfg.auto_terminate && cfg.ai_can_terminate)
      } catch { /* skip this frame */ } finally { busy = false }
    }, cfg.analysis_interval_seconds * 1000)
    return () => clearInterval(id)
  }, [ready, media.cam, cfg.ai_monitoring, cfg.analysis_interval_seconds]) // eslint-disable-line

  /* ---------- gate (needs a click for camera/fullscreen) ---------- */
  async function enter() {
    setGateErr('')
    if (needCam && !media.cam) { const ok = await media.request({ video: true, audio: cfg.microphone_required }); if (!ok) { setGateErr('Turn the camera on to continue.'); return } }
    if (cfg.fullscreen_required && !document.fullscreenElement) { try { await document.documentElement.requestFullscreen() } catch { setGateErr('Fullscreen was blocked by the browser. Click again.'); return } }
    setReady(true)
  }
  useEffect(() => { if (!needGate) setReady(true) }, []) // eslint-disable-line

  const q = questions[idx]
  const setAnswer = (id, v) => setAnswers((a) => { const n = { ...a }; if (v === '' || v == null || (Array.isArray(v) && !v.length)) delete n[id]; else n[id] = v; return n })
  const answeredCount = questions.filter((x) => answers[x.id] != null).length
  const sections = useMemo(() => { const g = []; questions.forEach((x, i) => { const s = x.section || ''; if (!g.length || g[g.length - 1].s !== s) g.push({ s, items: [] }); g[g.length - 1].items.push(i) }); return g }, [questions])

  if (!ready) return (
    <div className="cand-wrap"><div className="cand-card">
      <h1>{state.test.title}</h1><p className="muted-2 mb">Your test is in progress. Time left: <b>{clock(left)}</b>. The timer keeps running while you reconnect.</p>
      <ul className="hint mb" style={{ paddingLeft: 18 }}>{needCam && <li>Camera access is needed to continue.</li>}{cfg.fullscreen_required && <li>The test continues in fullscreen.</li>}</ul>
      {gateErr && <Alert tone="bad">{gateErr}</Alert>}{media.error && <Alert tone="bad">{media.error}</Alert>}
      <Button variant="primary" size="lg" onClick={enter} icon={Maximize}>Continue the test</Button>
    </div></div>
  )

  const urgent = left <= 60, low = left <= 300
  return (
    <div className="room">
      <header className="room-top">
        <div className="grow truncate"><b>{state.test.title}</b><span className="muted" style={{ marginLeft: 10, fontSize: 13 }}>{answeredCount}/{questions.length} answered</span></div>
        <ThemeToggle />
        <span className={`save ${save}`} role="status">{save === 'saved' ? 'All answers saved' : save === 'saving' ? 'Saving…' : <><WifiOff size={14} /> Offline — saved on this device</>}</span>
        <div className={`timer ${urgent ? 'urgent' : low ? 'low' : ''}`} role="timer" aria-label={`Time left ${clock(left)}`}>{clock(left)}</div>
        <Button variant="primary" icon={Send} onClick={() => setConfirm(true)}>Submit</Button>
      </header>

      <ProctorAlerts alerts={alerts} onDismiss={dismissAlert} />
      <div className="room-notices" aria-live="polite">
        {notices.slice(-3).map((n) => <Alert key={n.id} tone={n.tone}><Bell size={14} /> <b>From the organizer:</b> {n.text} <a href="#close" onClick={(e) => { e.preventDefault(); setNotices((x) => x.filter((m) => m.id !== n.id)) }}>Dismiss</a></Alert>)}
      </div>

      {questions.length > 0 && problems.length > 0 && <div className="tabs room-tabs"><button className={view === 'questions' ? 'active' : ''} onClick={() => setView('questions')}>Questions ({answeredCount}/{questions.length})</button><button className={view === 'coding' ? 'active' : ''} onClick={() => setView('coding')}>Coding ({problems.length})</button></div>}

      <div className="room-body">
        <main className="room-main">
          {view === 'questions' && q && (
            <article className="question" key={q.id}>
              <div className="row between"><span className="muted">Question {idx + 1} of {questions.length}{q.section ? ` · ${q.section}` : ''}</span><span className="muted">{q.marks} mark{q.marks === 1 ? '' : 's'}</span></div>
              <h2 style={{ whiteSpace: 'pre-wrap' }}>{q.text}</h2>
              {q.type === 'short_text' ? <input className="input" style={{ maxWidth: 520 }} autoComplete="off" aria-label="Your answer" placeholder="Type your answer" value={answers[q.id] || ''} onChange={(e) => setAnswer(q.id, e.target.value)} />
                : <div className="options" role={q.type === 'multiple' ? 'group' : 'radiogroup'} aria-label="Answer options">
                  {q.options.map((o, i) => {
                    const multi = q.type === 'multiple'; const cur = answers[q.id]; const on = multi ? (cur || []).includes(o) : cur === o
                    return <label key={i} className={`option ${on ? 'on' : ''}`}><input type={multi ? 'checkbox' : 'radio'} name={`q${q.id}`} checked={on} onChange={() => multi ? setAnswer(q.id, on ? cur.filter((x) => x !== o) : [...(cur || []), o]) : setAnswer(q.id, o)} /><span className="key">{String.fromCharCode(65 + i)}</span><span>{o}</span></label>
                  })}</div>}
              {q.type === 'multiple' && <p className="hint">Select all that apply.</p>}
              <div className="row between mt-lg" style={{ marginTop: 28 }}>
                <Button icon={ChevronLeft} disabled={idx === 0} onClick={() => setIdx(idx - 1)}>Previous</Button>
                <span className="row"><Button icon={Flag} className={flagged.includes(q.id) ? 'primary' : ''} onClick={() => setFlagged((f) => (f.includes(q.id) ? f.filter((x) => x !== q.id) : [...f, q.id]))}>{flagged.includes(q.id) ? 'Flagged for review' : 'Flag for review'}</Button>
                  {answers[q.id] != null && <Button variant="ghost" onClick={() => setAnswer(q.id, '')}>Clear</Button>}</span>
                {idx < questions.length - 1 ? <Button variant="primary" onClick={() => setIdx(idx + 1)}>Next <ChevronRight size={16} /></Button> : <Button variant="primary" onClick={() => setConfirm(true)}>Review & submit</Button>}
              </div>
            </article>
          )}
          {view === 'coding' && <CodingPanel problems={problems} attemptId={attemptId} />}
        </main>

        <aside className="room-side">
          {needCam && <CamTile video={video} camOn={media.cam} issue={hint} monitoring={!!cfg.ai_monitoring} />}
          {view === 'questions' && <nav aria-label="Question navigator">{sections.map((g, gi) => (
            <div key={gi}>{g.s && <div className="nav-sec">{g.s}</div>}<div className="qgrid">{g.items.map((i) => { const id = questions[i].id; return <button key={id} className={`qn ${i === idx ? 'cur' : ''} ${answers[id] != null ? 'ans' : ''} ${flagged.includes(id) ? 'flag' : ''}`} aria-label={`Question ${i + 1}${answers[id] != null ? ', answered' : ''}${flagged.includes(id) ? ', flagged' : ''}`} onClick={() => { setIdx(i); setView('questions') }}>{i + 1}</button> })}</div></div>))}
            <div className="legend mt"><span><i style={{ background: 'var(--accent)' }} />Answered</span><span><i style={{ background: 'var(--warn)' }} />Flagged</span><span><i style={{ background: 'var(--neutral-soft)' }} />Not answered</span></div></nav>}
        </aside>
      </div>

      {fsLost && cfg.fullscreen_required && (
        <div className="overlay" style={{ zIndex: 150 }}><div className="modal" role="alertdialog" aria-label="Return to fullscreen"><div className="body" style={{ textAlign: 'center', padding: 28 }}>
          <Maximize size={32} color="var(--bad)" /><h2 style={{ margin: '10px 0' }}>Return to fullscreen</h2><p className="muted-2 mb">You left fullscreen. This was recorded. The timer is still running.</p>
          <Button variant="primary" size="lg" onClick={() => document.documentElement.requestFullscreen().catch(() => {})}>Go back to fullscreen</Button></div></div></div>
      )}
      {confirm && (
        <Modal title="Submit your test?" onClose={() => setConfirm(false)} footer={<><Button onClick={() => setConfirm(false)}>Keep working</Button><Button variant="primary" busy={submitting} onClick={() => submit(false)}>Submit now</Button></>}>
          <p>You have answered <b>{answeredCount} of {questions.length}</b> questions{flagged.length ? ` and flagged ${flagged.length}` : ''}.</p>
          {answeredCount < questions.length && <Alert tone="warn" className="mt">{questions.length - answeredCount} question{questions.length - answeredCount === 1 ? ' is' : 's are'} unanswered.</Alert>}
          {problems.length > 0 && <p className="muted-2 mt">Coding problems are scored from your best submission so far.</p>}
          <p className="muted-2 mt">You cannot change answers after submitting.</p>
        </Modal>
      )}
    </div>
  )
}
