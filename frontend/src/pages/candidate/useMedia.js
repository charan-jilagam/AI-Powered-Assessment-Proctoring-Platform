import { useCallback, useEffect, useRef, useState } from 'react'

// Owns the camera/microphone for the whole exam session so the stream survives lobby -> exam.
export function useMedia() {
  const streamRef = useRef(null)
  const [state, setState] = useState({ cam: false, mic: false, error: '' })

  const request = useCallback(async ({ video, audio }) => {
    if (!video && !audio) return true
    if (!navigator.mediaDevices?.getUserMedia) { setState((s) => ({ ...s, error: 'This browser cannot access a camera. Use a recent Chrome, Edge or Firefox.' })); return false }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: video ? { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' } : false, audio: !!audio })
      streamRef.current?.getTracks().forEach((t) => t.stop())
      streamRef.current = stream
      stream.getTracks().forEach((t) => { t.onended = () => setState((s) => ({ ...s, cam: t.kind === 'video' ? false : s.cam, mic: t.kind === 'audio' ? false : s.mic })) })
      setState({ cam: stream.getVideoTracks().some((t) => t.readyState === 'live'), mic: stream.getAudioTracks().some((t) => t.readyState === 'live'), error: '' })
      return true
    } catch (e) {
      const msg = e.name === 'NotAllowedError' ? 'Access was blocked. Click the camera icon in the address bar, allow it, then try again.'
        : e.name === 'NotFoundError' ? 'No camera or microphone was found on this device.' : e.name === 'NotReadableError' ? 'Another app is using the camera. Close it and try again.' : `Could not start the camera (${e.name}).`
      setState((s) => ({ ...s, error: msg })); return false
    }
  }, [])

  const stop = useCallback(() => { streamRef.current?.getTracks().forEach((t) => t.stop()); streamRef.current = null; setState({ cam: false, mic: false, error: '' }) }, [])
  useEffect(() => () => streamRef.current?.getTracks().forEach((t) => t.stop()), [])

  // attach the stream to any <video> element
  const attach = useCallback((el) => { if (el && streamRef.current && el.srcObject !== streamRef.current) { el.srcObject = streamRef.current; el.play?.().catch(() => {}) } }, [])
  const capture = useCallback((videoEl, width = 320, quality = 0.6) => {
    const v = videoEl; if (!v || !v.videoWidth) return null
    const c = document.createElement('canvas'); c.width = width; c.height = Math.round((v.videoHeight / v.videoWidth) * width)
    c.getContext('2d').drawImage(v, 0, 0, c.width, c.height)
    return c.toDataURL('image/jpeg', quality)
  }, [])
  return { ...state, request, stop, attach, capture, streamRef }
}

// Rough "someone is talking" detector: sustained level above a threshold. Conservative on purpose.
export function watchVoice(stream, onVoice) {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext
    if (!Ctx || !stream.getAudioTracks().length) return () => {}
    const ctx = new Ctx(); const src = ctx.createMediaStreamSource(stream); const an = ctx.createAnalyser(); an.fftSize = 1024; src.connect(an)
    const buf = new Uint8Array(an.fftSize); let loud = 0
    const id = setInterval(() => {
      an.getByteTimeDomainData(buf)
      let sum = 0; for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v }
      const rms = Math.sqrt(sum / buf.length)
      loud = rms > 0.07 ? loud + 1 : Math.max(0, loud - 1)
      if (loud >= 12) { loud = 0; onVoice() }   // ~3 s of sustained sound (250 ms ticks)
    }, 250)
    return () => { clearInterval(id); ctx.close().catch(() => {}) }
  } catch { return () => {} }
}
