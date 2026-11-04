import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, AppWindow, Camera, CameraOff, ClipboardX, Expand, Keyboard, MousePointerClick, ScanFace, ShieldAlert, ShieldCheck, Smartphone, Users, Volume2, X } from 'lucide-react'

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
  MULTIPLE_PERSONS: { icon: Users, title: 'Another person is in the camera view', advice: 'You must be alone. Nobody else may be visible anywhere in the camera, even at the edge.' },
  PHONE_DETECTED: { icon: Smartphone, title: 'Mobile phone in the camera view', advice: 'Put your phone away, out of the room or out of sight, for the rest of the test.' },
  LOOKING_AWAY: { icon: ScanFace, title: 'Looking away from the screen', advice: 'Keep your eyes on the screen.' },
  LOOKING_DOWN: { icon: ScanFace, title: 'Looking down', advice: 'Keep your head and eyes facing the screen, not your lap or desk.' },
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

/** Live camera tile with a status chip. It shows the camera's ENTIRE view, uncropped, because the whole view is monitored.
 *  `issue`: current live finding label, if any. `boxes`: what the AI currently sees, as fractions of the frame. */
export function CamTile({ video, camOn, issue, monitoring, boxes = [] }) {
  const [ratio, setRatio] = useState(16 / 9)   // follows the real camera, so the preview is never cropped or stretched
  const state = !camOn ? 'off' : issue ? 'check' : monitoring ? 'ok' : 'idle'
  const text = { off: 'Camera off', check: issue, ok: 'Monitoring', idle: 'Camera on' }[state]
  const people = boxes.filter((b) => b.kind === 'person').length
  // the candidate's own outline is noise; show people only when there is more than one
  const shown = camOn ? boxes.filter((b) => b.kind !== 'person' || people > 1) : []
  const sync = (e) => { const v = e.currentTarget; if (v.videoWidth && v.videoHeight) setRatio(v.videoWidth / v.videoHeight) }
  return (
    <div className={`cam-tile ${state}`}>
      <div className="cam" style={{ aspectRatio: ratio }}>
        <video ref={video} muted playsInline autoPlay aria-label="Your camera" onLoadedMetadata={sync} onResize={sync} />
        {!camOn && <div className="ph"><Camera size={20} />Camera off</div>}
        {camOn && <span className="cam-guide" aria-hidden><i /><i /><i /><i /></span>}
        {shown.map((b, i) => (
          // the preview is mirrored, so mirror the box too
          <span key={i} className={`cam-box ${b.kind}${b.y < 0.07 ? ' edge' : ''}`} style={{ left: `${(1 - b.x - b.w) * 100}%`, top: `${b.y * 100}%`, width: `${b.w * 100}%`, height: `${b.h * 100}%` }}><em>{b.label}</em></span>
        ))}
      </div>
      <div className="cam-chip" role="status">
        {state === 'ok' ? <ShieldCheck size={14} /> : state === 'off' ? <CameraOff size={14} /> : state === 'check' ? <AlertTriangle size={14} /> : <Camera size={14} />}
        <span>{text}</span>{state === 'ok' && <i className="live-dot" aria-hidden />}
      </div>
      {state === 'check'
        ? <p className="cam-tip">The whole camera view is monitored. Look at the screen, and keep phones, notes and other people out of view.</p>
        : camOn && <p className="cam-tip">Everything this camera can see is monitored, including the edges.</p>}
    </div>
  )
}

