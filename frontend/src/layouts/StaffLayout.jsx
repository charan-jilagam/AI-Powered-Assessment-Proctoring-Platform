import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Bell as BellIcon, BookOpen, Building2, ChevronDown, Search, ClipboardList, CreditCard, FileClock, History, KeyRound, LayoutDashboard, LogOut, Mail, Menu, Settings, ShieldAlert, ShieldCheck, Users, UserCog, Inbox, UsersRound, Layers } from 'lucide-react'
import { useAuth } from '../lib/auth'
import { ThemeToggle } from '../lib/theme'
import { Alert, Avatar, Button, Loading } from '../ui'
import { api } from '../lib/api'
import { usePoll } from '../lib/hooks'
import { useSearch } from '../lib/useSearch'

const SUPER_NAV = [
  { to: '/super', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/super/organizations', label: 'Organizations', icon: Building2 },
  { to: '/super/plans', label: 'Plans', icon: Layers },
  { to: '/super/leads', label: 'Demo requests', icon: Inbox },
  { group: 'Platform' },
  { to: '/super/admins', label: 'Platform admins', icon: UserCog },
  { to: '/super/outbox', label: 'E-mail outbox', icon: Mail },
  { to: '/super/audit', label: 'Audit log', icon: History },
]
const ADMIN_NAV = [
  { to: '/app', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/app/tests', label: 'Tests', icon: ClipboardList },
  { to: '/app/review', label: 'Review queue', icon: ShieldAlert, badge: 'awaiting' },
  { to: '/app/candidates', label: 'Candidates', icon: UsersRound },
  { to: '/app/bank', label: 'Question bank', icon: BookOpen, admin: true },
  { group: 'Organization', admin: true },
  { to: '/app/team', label: 'Team', icon: Users, admin: true },
  { to: '/app/settings', label: 'Integrations', icon: KeyRound, admin: true },
  { to: '/app/billing', label: 'Plan & usage', icon: CreditCard, admin: true },
  { to: '/app/audit', label: 'Audit log', icon: FileClock, admin: true },
]

export function RequireRole({ role }) {
  const { status, user, notice } = useAuth()
  const loc = useLocation()
  if (status === 'loading') return <Loading />
  if (status === 'anon') return <Navigate to="/signin" state={{ from: loc.pathname + loc.search, notice }} replace />
  if (role === 'super' && user.role !== 'super_admin') return <Navigate to="/app" replace />
  if (role === 'org' && user.role === 'super_admin') return <Navigate to="/super" replace />
  return <StaffLayout />
}

function TopSearch() {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const nav = useNavigate()
  const res = useSearch(q)
  const has = res.tests.length + res.candidates.length > 0
  useEffect(() => {
    const key = (e) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); ref.current?.focus() } }
    const away = (e) => { if (!e.target.closest?.('.search')) setOpen(false) }
    window.addEventListener('keydown', key); document.addEventListener('mousedown', away)
    return () => { window.removeEventListener('keydown', key); document.removeEventListener('mousedown', away) }
  }, [])
  const go = (to) => { setOpen(false); setQ(''); nav(to) }
  return (
    <div className="search input-icon">
      <Search size={16} />
      <input ref={ref} className="input" placeholder="Search tests, candidates, or reports..." aria-label="Search" value={q}
        onChange={(e) => { setQ(e.target.value); setOpen(true) }} onFocus={() => setOpen(true)}
        onKeyDown={(e) => { if (e.key === 'Escape') { setOpen(false); e.target.blur() } if (e.key === 'Enter' && res.tests[0]) go(`/app/tests/${res.tests[0].id}`) }} />
      <kbd>Ctrl K</kbd>
      {open && q.trim().length >= 2 && (
        <div className="search-pop" role="listbox">
          {!has && <div className="empty-note muted" style={{ padding: 14 }}>No matches for "{q.trim()}"</div>}
          {res.tests.length > 0 && <h4>Tests</h4>}
          {res.tests.map((t) => <Link key={`t${t.id}`} to={`/app/tests/${t.id}`} onClick={() => go(`/app/tests/${t.id}`)}><ClipboardList size={15} />{t.title}<small>{t.status}</small></Link>)}
          {res.candidates.length > 0 && <h4>Candidates</h4>}
          {res.candidates.map((c) => <Link key={`c${c.id}`} to={`/app/candidates?q=${encodeURIComponent(c.email)}`} onClick={() => go(`/app/candidates?q=${encodeURIComponent(c.email)}`)}><UsersRound size={15} />{c.name}<small>{c.email}</small></Link>)}
        </div>
      )}
    </div>
  )
}

function Bell() {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState({ count: 0, items: [] })
  const load = () => api.get('/org/notifications').then(setData).catch(() => {})
  useEffect(() => { load() }, [])
  usePoll(load, 30000)
  useEffect(() => {
    const away = (e) => { if (!e.target.closest?.('.bell')) setOpen(false) }
    document.addEventListener('mousedown', away); return () => document.removeEventListener('mousedown', away)
  }, [])
  return (
    <div className="bell" style={{ position: 'relative' }}>
      <button type="button" className="icon-tile" aria-label={`Notifications${data.count ? `, ${data.count} new` : ''}`} onClick={() => setOpen((o) => !o)}>
        <BellIcon size={18} />{data.count > 0 && <i className="pip" />}
      </button>
      {open && (
        <div className="pop" role="menu">
          {data.items.length === 0 ? <div className="empty-note">You are all caught up.</div> : data.items.map((n, i) => (
            <Link key={i} to={n.to} onClick={() => setOpen(false)}><span className={`badge ${n.tone}`} style={{ flex: 'none' }}>{n.kind}</span><span>{n.text}</span></Link>
          ))}
        </div>
      )}
    </div>
  )
}

function VerifyBanner() {
  const { user, refresh } = useAuth()
  const [state, setState] = useState({ busy: false, msg: '', link: '', bad: false })
  async function resend() {
    setState({ busy: true, msg: '', link: '', bad: false })
    try {
      const r = await api.post('/auth/send-verification')
      if (r.status === 'already_verified') { await refresh(); return }
      setState({ busy: false, msg: `Verification link sent to ${user.email}. It stays valid for 48 hours.`, link: r.dev_link || '', bad: false })
    } catch (e) { setState({ busy: false, msg: e.message, link: '', bad: true }) }
  }
  async function check() {
    setState((s) => ({ ...s, busy: true }))
    try { await refresh() } finally { setState((s) => ({ ...s, busy: false, msg: s.msg || 'Not verified yet. Open the link in your e-mail first.' })) }
  }
  return (
    <Alert tone={state.bad ? 'bad' : 'warn'}>
      <b>Verify your e-mail to create tests.</b> We sent a link to {user.email}. Until you open it you can look around but not create, import or publish tests.
      <div className="row wrap" style={{ marginTop: 8, gap: 8 }}>
        <Button size="sm" onClick={resend} busy={state.busy}>Resend verification e-mail</Button>
        <Button size="sm" variant="ghost" onClick={check} disabled={state.busy}>I have verified</Button>
      </div>
      {state.msg && <div style={{ marginTop: 6 }}>{state.msg}</div>}
      {state.link && <div style={{ marginTop: 6, wordBreak: 'break-all' }}>Dev link: <a href={state.link}>{state.link}</a></div>}
    </Alert>
  )
}

function StaffLayout() {
  const { user, org, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const [menu, setMenu] = useState(false)
  const loc = useLocation()
  useEffect(() => setOpen(false), [loc.pathname])
  const isSuper = user.role === 'super_admin'
  const nav = (isSuper ? SUPER_NAV : ADMIN_NAV).filter((n) => !n.admin || user.role === 'admin')
  const roleLabel = { admin: 'Admin', reviewer: 'Reviewer', super_admin: 'Platform owner' }[user.role] || user.role

  return (
    <div className="shell">
      {open && <div className="scrim" onClick={() => setOpen(false)} />}
      <aside className={`side ${open ? 'open' : ''}`} aria-label="Main navigation">
        <Link to={isSuper ? '/super' : '/app'} className="brand" aria-label="ORVEXA home"><img src="/brand/orvexa-emblem.png" alt="" /><span className="wm">ORVEXA</span></Link>
        {!isSuper && org && <div className="org-chip"><span className="ico"><Building2 size={17} /></span><div><b>{org.name}</b><span>{org.plan_name} plan{org.status === 'trial' ? ' · trial' : ''}</span></div></div>}
        {isSuper && <div className="org-chip"><span className="ico"><ShieldCheck size={17} /></span><div><b>Platform console</b><span>Super admin</span></div></div>}
        <nav className="nav">
          {nav.map((n, i) => n.group ? <div className="nav-group" key={i}>{n.group}</div> : (
            <NavLink key={n.to} to={n.to} end={n.end}><n.icon size={18} />{n.label}</NavLink>
          ))}
        </nav>
        <div className="side-foot">
          <div className="who"><Avatar name={user.full_name} /><div style={{ minWidth: 0 }}><b className="truncate">{user.full_name}</b><span>{user.email}</span></div></div>
          <div className="row" style={{ justifyContent: 'space-between' }}><ThemeToggle onDark /><NavLink to="/account" className="btn ghost sm"><Settings size={15} />Account</NavLink></div>
        </div>
      </aside>
      <div className="main-col">
        <div className="topbar">
          <Button variant="ghost" icon={Menu} className="menu-btn" onClick={() => setOpen(true)} aria-label="Open menu" />
          <div className="grow" />
          {!isSuper && <TopSearch />}
          {!isSuper && <Bell />}
          <div style={{ position: 'relative' }} className="umenu">
            <button type="button" className="user-chip" onClick={() => setMenu((m) => !m)} aria-haspopup="menu" aria-expanded={menu}>
              <Avatar name={user.full_name} /><div><b>{user.full_name}</b><span>{isSuper ? roleLabel : (org?.name || roleLabel)}</span></div><ChevronDown size={15} color="var(--text-3)" />
            </button>
            {menu && (
              <div className="pop" role="menu" style={{ width: 220 }} onMouseLeave={() => setMenu(false)}>
                <Link to="/account" onClick={() => setMenu(false)}><Settings size={16} />Account &amp; password</Link>
                <Link to="/guide" target="_blank" onClick={() => setMenu(false)}><BookOpen size={16} />User guide</Link>
                <button type="button" className="item" onClick={logout}><LogOut size={16} />Sign out</button>
              </div>
            )}
          </div>
        </div>
        <main className="main">
          {!isSuper && org?.block_reason && <Alert tone="bad">{org.block_reason}</Alert>}
          {user.role === 'admin' && user.email_verified === false && <VerifyBanner />}
          {user.must_change_password && loc.pathname !== '/account' && <Alert tone="warn">You are using a temporary password. <Link to="/account">Set your own password</Link>.</Alert>}
          <Outlet />
        </main>
      </div>
    </div>
  )
}
