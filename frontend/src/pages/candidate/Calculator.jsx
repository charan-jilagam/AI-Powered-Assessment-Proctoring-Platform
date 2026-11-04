import { useRef, useState } from 'react'
import { X } from 'lucide-react'
import { evaluate, format } from '../../lib/calc'

/* On-screen calculator (the organizer switches it on per test). A draggable panel: type with the keyboard or tap the keys.
   Expressions are evaluated by lib/calc.js (no eval). % divides by 100, so "15%*240" is 36. */

const BASIC = [
  ['C', 'clear', 'fn'], ['⌫', 'back', 'fn'], ['%', '%', 'fn'], ['÷', '/', 'op'],
  ['7'], ['8'], ['9'], ['×', '*', 'op'],
  ['4'], ['5'], ['6'], ['−', '-', 'op'],
  ['1'], ['2'], ['3'], ['+', '+', 'op'],
  ['±', 'neg', 'fn'], ['0'], ['.'], ['=', 'eq', 'eq'],
]
const SCI = [
  ['sin', 'sin(', 'fn'], ['cos', 'cos(', 'fn'], ['tan', 'tan(', 'fn'], ['log', 'log(', 'fn'], ['ln', 'ln(', 'fn'],
  ['asin', 'asin(', 'fn'], ['acos', 'acos(', 'fn'], ['atan', 'atan(', 'fn'], ['√', 'sqrt(', 'fn'], ['x²', '^2', 'fn'],
  ['(', '(', 'fn'], [')', ')', 'fn'], ['xʸ', '^', 'fn'], ['n!', '!', 'fn'], ['1/x', 'inv', 'fn'],
  ['π', 'pi', 'fn'], ['e', 'e', 'fn'], ['MC', 'mc', 'mem'], ['MR', 'mr', 'mem'], ['M+', 'm+', 'mem'],
]

export default function Calculator({ mode = 'basic', onClose }) {
  const [expr, setExpr] = useState('')
  const [shown, setShown] = useState('0')        // result / error line
  const [degrees, setDegrees] = useState(true)
  const [mem, setMem] = useState(0)
  const [pos, setPos] = useState({ x: 24, y: 120 })
  const drag = useRef(null)
  const scientific = mode === 'scientific'

  const calc = (text = expr) => {
    if (!text.trim()) return null
    try { const v = evaluate(text, { degrees }); return { ok: true, v, s: format(v) } } catch { return { ok: false } }
  }
  const press = (code) => {
    if (code === 'clear') { setExpr(''); setShown('0'); return }
    if (code === 'back') { setExpr((x) => x.slice(0, -1)); return }
    if (code === 'eq') {
      const r = calc()
      if (!r) return
      if (r.ok) { setShown(r.s); setExpr(r.s) } else setShown('Error')
      return
    }
    if (code === 'neg') { setExpr((x) => (x.startsWith('-(') && x.endsWith(')') ? x.slice(2, -1) : x ? `-(${x})` : '-')); return }
    if (code === 'inv') { setExpr((x) => (x ? `1/(${x})` : '1/')); return }
    if (code === 'mc') { setMem(0); return }
    if (code === 'mr') { setExpr((x) => x + format(mem)); return }
    if (code === 'm+') { const r = calc(); if (r?.ok) setMem((m) => m + r.v); return }
    setExpr((x) => (shown !== '0' && x === shown && /^[0-9.]/.test(code) ? code : x + code))      // typing a digit after "=" starts fresh
    setShown('0')
  }
  const live = calc()
  const line = shown !== '0' ? shown : live?.ok ? live.s : expr ? '' : '0'

  const onKey = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); press('eq') }
    else if (e.key === 'Escape') onClose()
  }
  const down = (e) => { drag.current = { dx: e.clientX - pos.x, dy: e.clientY - pos.y }; e.currentTarget.setPointerCapture(e.pointerId) }
  const move = (e) => { if (drag.current) setPos({ x: Math.max(0, Math.min(window.innerWidth - 120, e.clientX - drag.current.dx)), y: Math.max(0, Math.min(window.innerHeight - 60, e.clientY - drag.current.dy)) }) }
  const up = () => { drag.current = null }

  return (
    <div className={`calc ${scientific ? 'sci' : ''}`} style={{ left: pos.x, top: pos.y }} role="dialog" aria-label="Calculator">
      <div className="calc-head" onPointerDown={down} onPointerMove={move} onPointerUp={up}>
        <b>Calculator</b>
        {scientific && <button type="button" className="calc-mode" onPointerDown={(e) => e.stopPropagation()} onClick={() => setDegrees((d) => !d)} aria-label="Angle unit" title="Angle unit for sin, cos, tan">{degrees ? 'DEG' : 'RAD'}</button>}
        {mem !== 0 && <span className="calc-m" title="Something is in memory">M</span>}
        <button type="button" className="calc-x" onPointerDown={(e) => e.stopPropagation()} onClick={onClose} aria-label="Close calculator"><X size={14} /></button>
      </div>
      <input className="calc-expr" value={expr} onChange={(e) => { setExpr(e.target.value); setShown('0') }} onKeyDown={onKey} placeholder="Type or tap" spellCheck={false} autoComplete="off" aria-label="Expression" />
      <output className={`calc-out ${shown === 'Error' || (expr && !live?.ok && shown === '0') ? 'dim' : ''}`} aria-live="polite">{shown === 'Error' ? 'Error' : line}</output>
      <div className="calc-keys">
        {scientific && <div className="calc-sci">{SCI.map(([label, code, kind]) => <button type="button" key={label} className={`k ${kind}`} onClick={() => press(code)}>{label}</button>)}</div>}
        <div className="calc-main">{BASIC.map(([label, code, kind]) => <button type="button" key={label} className={`k ${kind || ''}`} onClick={() => press(code || label)}>{label}</button>)}</div>
      </div>
    </div>
  )
}
