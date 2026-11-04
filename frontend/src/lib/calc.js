// A tiny, safe expression evaluator for the exam calculator (no eval / Function). Supports + - * / ^ ( ) % !, constants
// pi and e, and sin cos tan asin acos atan log ln sqrt cbrt abs exp. Implicit multiplication works: 2pi, 3(4+1), (2)(3).
const FUNCS = {
  sin: (x, d) => Math.sin(d ? (x * Math.PI) / 180 : x), cos: (x, d) => Math.cos(d ? (x * Math.PI) / 180 : x), tan: (x, d) => Math.tan(d ? (x * Math.PI) / 180 : x),
  asin: (x, d) => (d ? (Math.asin(x) * 180) / Math.PI : Math.asin(x)), acos: (x, d) => (d ? (Math.acos(x) * 180) / Math.PI : Math.acos(x)), atan: (x, d) => (d ? (Math.atan(x) * 180) / Math.PI : Math.atan(x)),
  log: (x) => Math.log10(x), ln: (x) => Math.log(x), sqrt: (x) => Math.sqrt(x), cbrt: (x) => Math.cbrt(x), abs: (x) => Math.abs(x), exp: (x) => Math.exp(x),
}
const CONSTS = { pi: Math.PI, e: Math.E }

function tokenize(src) {
  const s = src.replace(/×/g, '*').replace(/÷/g, '/').replace(/−/g, '-').replace(/π/g, 'pi').replace(/√/g, 'sqrt').replace(/\s+/g, '').toLowerCase()
  const out = []
  let i = 0
  while (i < s.length) {
    const ch = s[i]
    if (/[0-9.]/.test(ch)) {
      const m = /^(\d+\.?\d*|\.\d+)(e[+-]?\d+(?![a-z]))?/.exec(s.slice(i))
      if (!m || s[i + m[0].length] === '.') throw new Error('number')
      out.push({ t: 'n', v: Number(m[0]) }); i += m[0].length
    } else if (/[a-z]/.test(ch)) {
      const m = /^[a-z]+/.exec(s.slice(i))[0]
      if (m in CONSTS) out.push({ t: 'n', v: CONSTS[m] }); else if (m in FUNCS) out.push({ t: 'f', v: m }); else throw new Error('name')
      i += m.length
    } else if ('+-*/^()%!'.includes(ch)) { out.push({ t: ch }); i++ } else throw new Error('char')
  }
  return out
}

export function evaluate(src, { degrees = true } = {}) {
  const tk = tokenize(src)
  let open = 0
  for (const t of tk) { if (t.t === '(') open++; else if (t.t === ')' && --open < 0) throw new Error('paren') }
  while (open-- > 0) tk.push({ t: ')' })          // like a pocket calculator, unclosed brackets close themselves
  let p = 0
  const peek = () => tk[p]
  const eat = (t) => { if (peek()?.t === t) { p++; return true } return false }
  function expr() { let v = term(); for (;;) { if (eat('+')) v += term(); else if (eat('-')) v -= term(); else return v } }
  function term() {
    let v = unary()
    for (;;) {
      if (eat('*')) v *= unary()
      else if (eat('/')) { const d = unary(); if (d === 0) throw new Error('div0'); v /= d }
      else if (peek() && (peek().t === 'n' || peek().t === 'f' || peek().t === '(')) v *= unary()    // implicit multiplication
      else return v
    }
  }
  function unary() { if (eat('-')) return -unary(); if (eat('+')) return unary(); return power() }
  function power() { const b = postfix(); if (eat('^')) return Math.pow(b, unary()); return b }
  function postfix() {
    let v = primary()
    for (;;) {
      if (eat('%')) v /= 100
      else if (eat('!')) { if (v < 0 || !Number.isInteger(v) || v > 170) throw new Error('fact'); let f = 1; for (let k = 2; k <= v; k++) f *= k; v = f }
      else return v
    }
  }
  function primary() {
    const t = peek()
    if (!t) throw new Error('end')
    if (t.t === 'n') { p++; return t.v }
    if (t.t === 'f') { p++; const arg = eat('(') ? (() => { const a = expr(); if (!eat(')')) throw new Error('paren'); return a })() : power(); return FUNCS[t.v](arg, degrees) }
    if (eat('(')) { const v = expr(); if (!eat(')')) throw new Error('paren'); return v }
    throw new Error('syntax')
  }
  const v = expr()
  if (p !== tk.length) throw new Error('syntax')
  if (!Number.isFinite(v)) throw new Error('range')
  return v
}

// 12 significant digits, no floating-point dust (0.1 + 0.2 -> 0.3), exponent form only for very large / small values
export function format(v) {
  if (Object.is(v, -0)) return '0'
  const r = Number(v.toPrecision(12))
  const a = Math.abs(r)
  return a !== 0 && (a >= 1e12 || a < 1e-9) ? r.toExponential(6).replace(/\.?0+e/, 'e') : String(r)
}
