import { useEffect, useRef } from 'react'
import { AlertTriangle, AppWindow, Camera, CameraOff, ClipboardX, Expand, Keyboard, MousePointerClick, ScanFace, ShieldAlert, ShieldCheck, Users, Volume2, X } from 'lucide-react'

// What the candidate is told for each recorded event. The server decides severity; this is wording only.
const INFO = {
  TAB_SWITCH: { icon: AppWindow, title: 'You left the exam tab', advice: 'Stay on this tab for the whole test.' },
  WINDOW_BLUR: { icon: AppWindow, title: 'Exam window lost focus', advice: 'Click back into the test and avoid other windows.' },
  FULLSCREEN_EXIT: { icon: Expand, title: 'You exited fullscreen', advice: 'Return to fullscreen and stay there.' },
  COPY_PASTE: { icon: ClipboardX, title: 'Copy and paste are disabled', advice: 'Type your answers yourself.' },
  RIGHT_CLICK: { icon: MousePointerClick, title: 'Right-click is disabled', advice: 'Use the buttons on the page.' },
  SHORTCUT: { icon: Keyboard, title: 'That shortcut is blocked', advice: 'Keyboard shortcuts for developer tools or printing are not allowed.' },
  DEVTOOLS: { icon: Keyboard, title: 'Developer tools suspected', advice: 'Close developer tools.' },
  SCREEN_RESIZE: { icon: Expand, title: 'Window size changed', advice: 'Keep the window at its original size.' },
  CAMERA_LOST: { icon: CameraOff, title: 'Your camera stopped', advice: 'Reconnect or allow the camera to continue.' },
  MIC_LOST: { icon: Volume2, title: 'Your microphone stopped', advice: 'Reconnect or allow the microphone.' },
  AUDIO_VOICE: { icon: Volume2, title: 'Talking detected', advice: 'Please stay quiet during the test.' },
  NO_FACE: { icon: ScanFace, title: 'We cannot see your face', advice: 'Sit in front of the camera with your face fully visible.' },
  MULTIPLE_FACES: { icon: Users, title: 'More than one person in view', advice: 'You must be alone during the test.' },
  LOOKING_AWAY: { icon: ScanFace, title: 'Looking away from the screen', advice: 'Keep your eyes on the screen.' },
  HEAD_TURNED: { icon: ScanFace, title: 'Head turned away', advice: 'Face the screen.' },
  LIP_MOVEMENT: { icon: Volume2, title: 'Possible speaking detected', advice: 'Please do not speak during the test.' },
  PROHIBITED_OBJECT: { icon: ShieldAlert, title: 'Prohibited object in view', advice: 'Remove phones, books and other devices from view.' },
  CAMERA_COVERED: { icon: CameraOff, title: 'Camera view is blocked or too dark', advice: 'Uncover the camera and improve the lighting.' },
}
// eslint-disable-next-line react-refresh/only-export-components
export const infoFor = (code, label) => ({ icon: AlertTriangle, title: label || 'Activity recorded', advice: 'This has been recorded for the organizer.', ...INFO[code] })

const MINOR_MS = 7000

/** Alert stack. `alerts`: [{ id, code, label, severity, n, max, auto }]. Serious alerts stay until acknowledged. */
export function ProctorAlerts({ alerts, onDismiss }) {
  return (
    <div className="pa-stack" aria-live="assertive" aria-relevant="additions">
      {alerts.slice(-3).map((a) => <AlertCard key={a.id} a={a} onDismiss={onDismiss} />)}
    </div>
  )
}

function AlertCard({ a, onDismiss }) {
  const serious = a.severity === 2
  const { icon: Icon, title, advice } = infoFor(a.code, a.label)
  const ref = useRef(onDismiss); ref.current = onDismiss
  useEffect(() => {
    if (serious) return
    const t = setTimeout(() => ref.current(a.id), MINOR_MS)
    return () => clearTimeout(t)
  }, [a.id, serious])
  return (
    <div className={`pa-card ${serious ? 'serious' : 'minor'}`} role={serious ? 'alertdialog' : 'status'} aria-label={title}>
      <span className="pa-icon"><Icon size={20} /></span>
      <div className="pa-body">
        <div className="pa-kicker">{serious ? 'Serious warning' : 'Notice'}</div>
        <b>{title}</b>
        <p>{advice}</p>
        {serious && a.max > 0 && (
          <div className="pa-strikes" aria-label={`Serious warning ${a.n} of ${a.max}`}>
            <span className="pips">{Array.from({ length: a.max }, (_, i) => <i key={i} className={i < a.n ? 'used' : ''} />)}</span>
            <span>{a.n} of {a.max}{a.auto ? ' — the test ends at ' + a.max : ''}</span>
          </div>
        )}
        {serious && <button type="button" className="pa-ack" onClick={() => onDismiss(a.id)}>I understand</button>}
      </div>
      {!serious && <button type="button" className="pa-x" aria-label="Dismiss" onClick={() => onDismiss(a.id)}><X size={14} /></button>}
      {!serious && <span className="pa-timer" style={{ animationDuration: `${MINOR_MS}ms` }} />}
    </div>
  )
}

/** Live camera tile with a status chip and a face guide. `issue`: current live finding label, if any. */
export function CamTile({ video, camOn, issue, monitoring }) {
  const state = !camOn ? 'off' : issue ? 'check' : monitoring ? 'ok' : 'idle'
  const text = { off: 'Camera off', check: issue, ok: 'Monitoring', idle: 'Camera on' }[state]
  return (
    <div className={`cam-tile ${state}`}>
      <div className="cam"><video ref={video} muted playsInline autoPlay aria-label="Your camera" />
        {!camOn && <div className="ph"><Camera size={20} />Camera off</div>}
        {camOn && <span className="cam-guide" aria-hidden><i /><i /><i /><i /></span>}
      </div>
      <div className="cam-chip" role="status">
        {state === 'ok' ? <ShieldCheck size={14} /> : state === 'off' ? <CameraOff size={14} /> : state === 'check' ? <AlertTriangle size={14} /> : <Camera size={14} />}
        <span>{text}</span>{state === 'ok' && <i className="live-dot" aria-hidden />}
      </div>
      {state === 'check' && <p className="cam-tip">Look at the screen and keep only your face in view.</p>}
    </div>
  )
}

