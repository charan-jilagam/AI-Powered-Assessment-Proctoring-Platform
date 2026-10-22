const dtf = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })
const df = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })
// The API sends naive UTC timestamps for some fields; treat a missing zone as UTC.
export const toDate = (v) => (v ? new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(v) ? v : v + 'Z') : null)
export const fmtDateTime = (v) => (v ? dtf.format(toDate(v)) : '—')
export const fmtDate = (v) => (v ? df.format(toDate(v)) : '—')
export function ago(v) {
  if (!v) return '—'
  const s = Math.max(0, (Date.now() - toDate(v).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return `${Math.floor(s / 86400)} d ago`
}
export const pct = (v) => (v === null || v === undefined ? '—' : `${Math.round(v * 10) / 10}%`)
export const num = (v) => (v === null || v === undefined ? '—' : Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100))
export const money = (v, cur = 'USD') => new Intl.NumberFormat(undefined, { style: 'currency', currency: cur, maximumFractionDigits: 0 }).format(v || 0)
export function clock(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds))
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60
  const mm = String(m).padStart(2, '0'), ss = String(r).padStart(2, '0')
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}
export const duration = (sec) => (sec == null ? '—' : sec < 90 ? `${sec}s` : `${Math.round(sec / 60)} min`)
export const limitText = (n) => (n === -1 ? 'Unlimited' : String(n))
export const titleCase = (s) => (s || '').replace(/[_.]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
// toInput/fromInput convert between API UTC and <input type="datetime-local"> (local time)
export function toLocalInput(v) {
  if (!v) return ''
  const d = toDate(v); const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}
export const fromLocalInput = (v) => (v ? new Date(v).toISOString() : null)
