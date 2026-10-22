import { useEffect, useRef, useState } from 'react'
import { Camera, CheckCircle2, Circle, ScanFace, ShieldCheck } from 'lucide-react'
import { cand } from '../../lib/api'
import { Alert, Button } from '../../ui'
import { Brand } from './Join'

export default function Lobby({ state, media, onStarted }) {
  const t = state.test, cfg = t.proctoring_config
  const [consent, setConsent] = useState(false)
  const [ids, setIds] = useState({ id: null, face: null })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [fsOk, setFsOk] = useState(!cfg.fullscreen_required || !!document.fullscreenEnabled)
  const video = useRef(null)
  const needCam = cfg.webcam_required || cfg.id_verification
  const camReady = !needCam || media.cam
  const micReady = !cfg.microphone_required || media.mic
  const idReady = !cfg.id_verification || (ids.id && ids.face)
  const ready = camReady && micReady && idReady && consent && fsOk

  useEffect(() => { if (media.cam) media.attach(video.current) }, [media.cam]) // eslint-disable-line
  useEffect(() => setFsOk(!cfg.fullscreen_required || !!document.fullscreenEnabled), [cfg.fullscreen_required])

  const snap = (kind) => { const img = media.capture(video.current, 480, 0.7); if (img) setIds((x) => ({ ...x, [kind]: img })) }

  async function start() {
    setBusy(true); setErr('')
    try {
      if (cfg.fullscreen_required) await document.documentElement.requestFullscreen?.().catch(() => {})
      const s = await cand.post('/attempt/start', {
        consent: true, id_image: ids.id || undefined, face_image: ids.face || undefined,
        system_info: { browser: navigator.userAgent.slice(0, 120), screen: `${screen.width}x${screen.height}`, language: navigator.language, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, camera: String(media.cam), microphone: String(media.mic) },
      })
      onStarted(s)
    } catch (e) { setErr(e.message); setBusy(false) }
  }

  const Row = ({ ok, children }) => <li className="row" style={{ alignItems: 'flex-start' }}>{ok ? <CheckCircle2 size={18} color="var(--ok)" /> : <Circle size={18} color="var(--line-strong)" />}<span>{children}</span></li>

  return (
    <div className="cand-wrap">
      <div className="cand-card wide">
        <Brand org={t.organization} />
        <h1>{t.title}</h1>
        <p className="muted-2">Hello {state.candidate.name}. You have <b>{t.duration_minutes} minutes</b> once you press Start. The timer cannot be paused.</p>
        {t.instructions && <div className="instructions"><h3>Instructions from the organizer</h3><p style={{ whiteSpace: 'pre-wrap' }}>{t.instructions}</p></div>}

        <h3 className="mt-lg" style={{ marginTop: 22 }}>Before you start</h3>
        <ul style={{ listStyle: 'none', padding: 0, display: 'grid', gap: 10, margin: '12px 0 18px' }}>
          <Row ok={camReady && micReady}>{needCam || cfg.microphone_required ? 'Your camera' + (cfg.microphone_required ? ' and microphone' : '') + ' must be on for the whole test.' : 'No camera is needed for this test.'}</Row>
          {cfg.fullscreen_required && <Row ok={fsOk}>The test runs in fullscreen. Leaving fullscreen is recorded.</Row>}
          <Row ok>Switching tabs or windows{cfg.block_copy_paste ? ', copying and pasting' : ''} is recorded and shown to the organizer.</Row>
          {cfg.auto_terminate && <Row ok>After {cfg.max_level2_violations} serious warnings the test ends automatically.</Row>}
          <Row ok>Your answers save automatically. If your connection drops, rejoin with the same e-mail and continue.</Row>
        </ul>

        {needCam && (
          <div className="syscheck">
            <div className="preview"><video ref={video} muted playsInline autoPlay aria-label="Camera preview" />{!media.cam && <div className="ph"><Camera size={28} /><span>Camera is off</span></div>}</div>
            <div>
              {!media.cam || (cfg.microphone_required && !media.mic)
                ? <><p className="mb">Allow camera{cfg.microphone_required ? ' and microphone' : ''} access so we can check your setup.</p><Button icon={Camera} variant="primary" onClick={() => media.request({ video: true, audio: cfg.microphone_required })}>Turn on camera</Button></>
                : <Alert tone="ok">Camera{cfg.microphone_required ? ' and microphone are' : ' is'} working. Make sure your face is clearly visible and well lit.</Alert>}
              {media.error && <Alert tone="bad" className="mt">{media.error}</Alert>}
              {cfg.id_verification && media.cam && (
                <div className="mt"><h3 className="mb">Verify your identity</h3>
                  <div className="row wrap"><Button icon={ScanFace} onClick={() => snap('face')}>{ids.face ? 'Retake face photo' : 'Take face photo'}</Button><Button onClick={() => snap('id')}>{ids.id ? 'Retake ID photo' : 'Photograph your ID (hold it up)'}</Button></div>
                  <div className="row mt">{ids.face && <img src={ids.face} alt="Your face" style={{ height: 70, borderRadius: 6 }} />}{ids.id && <img src={ids.id} alt="Your ID" style={{ height: 70, borderRadius: 6 }} />}</div></div>)}
            </div>
          </div>
        )}
        {cfg.fullscreen_required && !document.fullscreenEnabled && <Alert tone="bad">This browser does not allow fullscreen, which this test requires. Try desktop Chrome, Edge or Firefox.</Alert>}

        <label className="check mt"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} /><span>I agree to be monitored during this test{cfg.webcam_required ? ', including photos from my webcam' : ''}, and to the organizer reviewing the recording of my activity.</span></label>
        {err && <Alert tone="bad" className="mt">{err}</Alert>}
        <Button className="mt" variant="primary" size="lg" icon={ShieldCheck} disabled={!ready} busy={busy} onClick={start}>Start the test</Button>
        {!ready && <p className="hint mt">{!camReady ? 'Turn on your camera to continue.' : !micReady ? 'Allow the microphone to continue.' : !idReady ? 'Take both photos to continue.' : !consent ? 'Tick the agreement to continue.' : ''}</p>}
      </div>
    </div>
  )
}
