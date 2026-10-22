import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { AlertTriangle, Check, ChevronLeft, ChevronRight, Copy, Info, Loader2, Search, X, CircleCheck, CircleAlert } from 'lucide-react'

export const cx = (...a) => a.filter(Boolean).join(' ')

/* ---------------- basic controls ---------------- */
export function Button({ variant, size, block, busy, icon: Icon, children, className, disabled, ...rest }) {
  return (
    <button type="button" {...rest} disabled={disabled || busy} className={cx('btn', variant, size, block && 'block', className)}>
      {busy ? <Loader2 size={15} className="spin-icon" style={{ animation: 'spin .7s linear infinite' }} /> : Icon ? <Icon size={size === 'sm' ? 14 : 16} /> : null}
      {children}
    </button>
  )
}
export const IconButton = ({ icon: Icon, label, ...p }) => (
  <Button {...p} className={cx('icon-btn', 'ghost', p.className)} aria-label={label} title={label}><Icon size={17} /></Button>
)

export function Field({ label, hint, error, children, className }) {
  const id = useId()
  const child = typeof children === 'function' ? children(id) : children
  return (
    <div className={cx('field', className)}>
      {label && <label htmlFor={id}>{label}</label>}
      {child}
      {error ? <span className="err-text">{error}</span> : hint ? <span className="hint">{hint}</span> : null}
    </div>
  )
}
export const Input = ({ label, hint, error, className, icon: Icon, ...p }) => (
  <Field label={label} hint={hint} error={error} className={className}>
    {(id) => Icon ? <div className="input-icon"><Icon size={16} /><input id={id} className="input" {...p} /></div> : <input id={id} className="input" {...p} />}
  </Field>
)
export const Textarea = ({ label, hint, error, className, ...p }) => (
  <Field label={label} hint={hint} error={error} className={className}>{(id) => <textarea id={id} className="input" {...p} />}</Field>
)
export const Select = ({ label, hint, error, className, children, ...p }) => (
  <Field label={label} hint={hint} error={error} className={className}>{(id) => <select id={id} className="input" {...p}>{children}</select>}</Field>
)
export const Check_ = ({ label, hint, ...p }) => (
  <label className="check"><input type="checkbox" {...p} /><span>{label}{hint && <small>{hint}</small>}</span></label>
)
export const Toggle = ({ title, desc, checked, onChange, disabled }) => (
  <div className="switch">
    <div><div className="t">{title}</div>{desc && <div className="d">{desc}</div>}</div>
    <label className="toggle"><input type="checkbox" role="switch" checked={!!checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} aria-label={title} /><span /></label>
  </div>
)
export function SearchBox({ value, onChange, placeholder = 'Search' }) {
  const [v, setV] = useState(value || '')
  useEffect(() => setV(value || ''), [value])
  useEffect(() => { const t = setTimeout(() => v !== (value || '') && onChange(v), 300); return () => clearTimeout(t) }, [v]) // eslint-disable-line
  return <div className="input-icon"><Search size={16} /><input className="input" type="search" value={v} placeholder={placeholder} aria-label={placeholder} onChange={(e) => setV(e.target.value)} /></div>
}

/* ---------------- display ---------------- */
const STATUS = {
  active: 'ok', published: 'ok', submitted: 'ok', completed: 'ok', passed: 'ok', pass: 'ok', cleared: 'ok', sent: 'ok', confirmed: 'ok', true: 'ok',
  trial: 'info', in_progress: 'info', registered: 'info', pending: 'info', started: 'info', queued: 'info', open: 'info', logged: 'info', new: 'info',
  draft: '', archived: '', closed: '', voided: '', revoked: '', dismissed: '', contacted: '',
  suspended: 'warn', suspicious: 'warn', warn: 'warn',
  cancelled: 'bad', terminated: 'bad', failed: 'bad', fail: 'bad', disqualified: 'bad', false: 'bad',
}
const LABEL = { in_progress: 'In progress', pass: 'Passed', fail: 'Failed', registered: 'In lobby', super_admin: 'Super admin', admin: 'Admin', reviewer: 'Reviewer' }
export function Badge({ tone, children, status, dot }) {
  const t = tone ?? (status !== undefined ? STATUS[String(status).toLowerCase()] : '')
  const text = children ?? LABEL[status] ?? String(status).replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
  return <span className={cx('badge', t)}>{dot && <i className={cx('dot', status === 'in_progress' && 'live')} />}{text}</span>
}
export function RiskMeter({ score = 0, level }) {
  const lv = level || (score >= 40 ? 'high' : score >= 15 ? 'medium' : 'low')
  return <span className={cx('risk', lv)} title={`Risk ${lv}`}><span className="bar"><i style={{ width: `${Math.min(100, score)}%` }} /></span>{score}</span>
}
export const Avatar = ({ name }) => <span className="avatar" aria-hidden>{(name || '?').split(/\s+/).slice(0, 2).map((s) => s[0]).join('').toUpperCase()}</span>
export const Spinner = () => <span className="spinner" role="status" aria-label="Loading" />
export const Loading = () => <div className="loading"><Spinner /></div>
export function Empty({ title, children, action }) {
  return <div className="empty"><h3>{title}</h3>{children && <p>{children}</p>}{action}</div>
}
export function Alert({ tone = 'info', children, className }) {
  const Icon = tone === 'ok' ? CircleCheck : tone === 'info' ? Info : tone === 'bad' ? CircleAlert : AlertTriangle
  return <div className={cx('alert', tone, className)} role={tone === 'bad' ? 'alert' : undefined}><Icon size={16} /><div>{children}</div></div>
}
export function Meter({ used, limit, label }) {
  const unlimited = limit === -1
  const ratio = unlimited || !limit ? 0 : used / limit
  return (
    <div>
      <div className="row between" style={{ fontSize: 13, marginBottom: 5 }}><span>{label}</span><span className="muted-2">{used} / {unlimited ? 'unlimited' : limit}</span></div>
      <div className={cx('meter', ratio >= 1 ? 'bad' : ratio >= 0.8 ? 'warn' : '')}><i style={{ width: `${Math.min(100, ratio * 100)}%` }} /></div>
    </div>
  )
}
export function PageHeader({ title, subtitle, children, crumbs }) {
  return (
    <div className="page-head">
      <div>
        {crumbs && <div className="crumbs">{crumbs.map((c, i) => <span key={i}>{c.to ? <Link to={c.to}>{c.label}</Link> : c.label}{i < crumbs.length - 1 && ' /'}</span>)}</div>}
        <h1>{title}</h1>{subtitle && <p>{subtitle}</p>}
      </div>
      {children && <div className="row wrap">{children}</div>}
    </div>
  )
}
export const Stats = ({ items }) => (
  <div className="stats">{items.map((s, i) => (
    <div className="stat" key={i}><div className="v">{s.value}</div><div className="l">{s.label}</div>{s.sub && <div className="s">{s.sub}</div>}</div>
  ))}</div>
)
export const Panel = ({ title, actions, children, flush, className }) => (
  <section className={cx('panel', className)}>
    {(title || actions) && <div className="ph"><h3>{title}</h3><div className="row">{actions}</div></div>}
    <div className={flush ? undefined : 'pb'}>{children}</div>
  </section>
)
export function Tabs({ tabs, active, onChange }) {
  return <div className="tabs" role="tablist">{tabs.map((t) => (
    <button key={t.id} role="tab" aria-selected={active === t.id} className={active === t.id ? 'active' : ''} onClick={() => onChange(t.id)}>{t.label}{t.count != null && <span className="badge">{t.count}</span>}</button>
  ))}</div>
}
export function Pager({ page, pageSize, total, onPage }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (total <= pageSize) return total ? <div className="pager"><span>{total} total</span></div> : null
  const from = (page - 1) * pageSize + 1, to = Math.min(total, page * pageSize)
  return (
    <div className="pager">
      <span>{from}–{to} of {total}</span>
      <span className="row"><Button size="sm" icon={ChevronLeft} disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page" />
        <span>Page {page} of {pages}</span>
        <Button size="sm" icon={ChevronRight} disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page" /></span>
    </div>
  )
}

/* ---------------- test code ticket ---------------- */
export function CodeTicket({ code, display, small }) {
  const [done, setDone] = useState(false)
  const shown = display || (code ? `${code.slice(0, 4)}-${code.slice(4)}` : '')
  return (
    <span className={cx('ticket', small && 'sm')}>
      <span className="code" aria-label={`Test code ${shown.replace('-', ' ')}`}>{shown}</span>
      <button type="button" title="Copy code" aria-label="Copy test code" onClick={async () => { try { await navigator.clipboard.writeText(code); setDone(true); setTimeout(() => setDone(false), 1500) } catch { /* clipboard blocked */ } }}>
        {done ? <Check size={16} /> : <Copy size={16} />}
      </button>
    </span>
  )
}
export function CopyButton({ text, label = 'Copy', size = 'sm' }) {
  const [done, setDone] = useState(false)
  return <Button size={size} icon={done ? Check : Copy} onClick={async () => { try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500) } catch { /* ignore */ } }}>{done ? 'Copied' : label}</Button>
}

/* ---------------- modal ---------------- */
export function Modal({ title, onClose, children, footer, wide, dismissable = true }) {
  const ref = useRef(null)
  useEffect(() => {
    const prev = document.activeElement
    const onKey = (e) => { if (e.key === 'Escape' && dismissable) onClose() }
    document.addEventListener('keydown', onKey)
    ref.current?.querySelector('input,select,textarea,button:not(.icon-btn)')?.focus()
    return () => { document.removeEventListener('keydown', onKey); prev?.focus?.() }
  }, []) // eslint-disable-line
  return createPortal(
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && dismissable && onClose()}>
      <div className={cx('modal', wide && 'wide')} role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <header><h2>{title}</h2>{dismissable && <IconButton icon={X} label="Close" onClick={onClose} />}</header>
        <div className="body">{children}</div>
        {footer && <footer>{footer}</footer>}
      </div>
    </div>, document.body)
}

/* ---------------- toast + confirm ---------------- */
const Ctx = createContext(null)
export const useUI = () => useContext(Ctx)
export function UIProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const [dialog, setDialog] = useState(null)
  const toast = useCallback((message, kind = 'ok') => {
    const id = Math.random()
    setToasts((t) => [...t, { id, message, kind }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === 'error' ? 7000 : 3500)
  }, [])
  const confirm = useCallback((o) => new Promise((resolve) => setDialog({ ...o, resolve })), [])
  const close = (v) => { dialog.resolve(v); setDialog(null) }
  return (
    <Ctx.Provider value={{ toast, error: (e) => toast(e?.message || String(e), 'error'), confirm }}>
      {children}
      <div className="toasts" aria-live="polite">{toasts.map((t) => <div key={t.id} className={cx('toast', t.kind === 'error' && 'error')}>{t.kind === 'error' ? <CircleAlert size={16} /> : <CircleCheck size={16} />}<span>{t.message}</span></div>)}</div>
      {dialog && (
        <Modal title={dialog.title} onClose={() => close(false)}
          footer={<><Button onClick={() => close(false)}>{dialog.cancelLabel || 'Cancel'}</Button><Button variant={dialog.danger ? 'danger' : 'primary'} onClick={() => close(true)}>{dialog.confirmLabel || 'Confirm'}</Button></>}>
          <p className="muted-2">{dialog.message}</p>
        </Modal>
      )}
    </Ctx.Provider>
  )
}

/* ---------------- data loading hook ---------------- */
export function useLoad(fn, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const run = useCallback(async () => {
    try { const data = await fn(); setState({ data, error: null, loading: false }); return data }
    catch (error) { setState((s) => ({ ...s, error, loading: false })) }
  }, deps) // eslint-disable-line
  useEffect(() => { setState((s) => ({ ...s, loading: true })); let live = true; run().then(() => live); return () => { live = false } }, [run])
  return { ...state, reload: run, setData: (d) => setState((s) => ({ ...s, data: typeof d === 'function' ? d(s.data) : d })) }
}
export function Async({ state, children }) {
  if (state.loading && !state.data) return <Loading />
  if (state.error && !state.data) return <Alert tone="bad">{state.error.message} <a href="#retry" onClick={(e) => { e.preventDefault(); state.reload() }}>Try again</a></Alert>
  return children(state.data)
}
