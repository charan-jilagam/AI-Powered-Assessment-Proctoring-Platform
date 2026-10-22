// One place for every network call. Staff and candidate sessions are kept apart on purpose:
// staff tokens live in localStorage (survive restarts), the candidate token lives in sessionStorage
// (one exam window = one session) so a shared lab computer never keeps a candidate logged in.
const BASE = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '')

const safe = (fn, fallback = null) => { try { return fn() } catch { return fallback } }
export const staffToken = {
  get: () => safe(() => localStorage.getItem('pai_staff')),
  set: (t) => safe(() => localStorage.setItem('pai_staff', t)),
  clear: () => safe(() => localStorage.removeItem('pai_staff')),
}
export const candToken = {
  get: () => safe(() => sessionStorage.getItem('pai_cand')),
  set: (t) => safe(() => sessionStorage.setItem('pai_cand', t)),
  clear: () => safe(() => sessionStorage.removeItem('pai_cand')),
}

export class ApiError extends Error {
  constructor(message, status, code) { super(message); this.status = status; this.code = code }
}

let onStaffExpired = () => {}
export const setStaffExpiredHandler = (fn) => { onStaffExpired = fn }
let onCandidateExpired = () => {}
export const setCandidateExpiredHandler = (fn) => { onCandidateExpired = fn }

function qs(params) {
  const p = new URLSearchParams()
  Object.entries(params || {}).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') p.set(k, v) })
  const s = p.toString()
  return s ? `?${s}` : ''
}

async function request(path, { method = 'GET', body, params, as = 'staff', raw = false, keepalive = false } = {}) {
  const headers = {}
  const token = as === 'staff' ? staffToken.get() : as === 'candidate' ? candToken.get() : null
  if (token) headers.Authorization = `Bearer ${token}`
  let payload
  if (body instanceof FormData) payload = body
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body) }

  let res
  try {
    res = await fetch(`${BASE}${path}${qs(params)}`, { method, headers, body: payload, keepalive })
  } catch {
    throw new ApiError('Cannot reach the server. Check your internet connection.', 0, 'network')
  }
  if (raw && res.ok) return res
  let data = null
  const text = await res.text()
  if (text) { try { data = JSON.parse(text) } catch { data = { detail: text.slice(0, 200) } } }
  if (!res.ok) {
    const msg = typeof data?.detail === 'string' ? data.detail
      : Array.isArray(data?.detail) ? data.detail.map((e) => e.msg).join('; ') : `Request failed (${res.status})`
    if (res.status === 401 && token) (as === 'staff' ? onStaffExpired : onCandidateExpired)(msg)
    throw new ApiError(msg, res.status, data?.code || 'error')
  }
  return data
}

export const api = {
  get: (p, params, o) => request(p, { ...o, params }),
  post: (p, body, o) => request(p, { ...o, method: 'POST', body: body ?? {} }),
  put: (p, body, o) => request(p, { ...o, method: 'PUT', body }),
  patch: (p, body, o) => request(p, { ...o, method: 'PATCH', body }),
  del: (p, o) => request(p, { ...o, method: 'DELETE' }),
  // downloads a protected file (CSV export, evidence image) with the staff token
  async download(path, filename) {
    const res = await request(path, { raw: true })
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = Object.assign(document.createElement('a'), { href: url, download: filename })
    document.body.appendChild(a); a.click(); a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 5000)
  },
  async blobUrl(path) {
    const res = await request(path, { raw: true })
    return URL.createObjectURL(await res.blob())
  },
}
// candidate-scoped helpers
export const cand = {
  get: (p, params) => request(p, { params, as: 'candidate' }),
  post: (p, body, o) => request(p, { ...o, method: 'POST', body: body ?? {}, as: 'candidate' }),
  put: (p, body) => request(p, { method: 'PUT', body, as: 'candidate' }),
}
export const pub = {
  get: (p, params) => request(p, { params, as: 'none' }),
  post: (p, body) => request(p, { method: 'POST', body: body ?? {}, as: 'none' }),
}
