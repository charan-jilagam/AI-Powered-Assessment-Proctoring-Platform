import { useEffect, useState } from 'react'
import { Link, NavLink, Navigate, Outlet, useLocation } from 'react-router-dom'
import { BookOpen, Building2, ClipboardList, CreditCard, FileClock, History, KeyRound, LayoutDashboard, LogOut, Mail, Menu, Settings, ShieldAlert, ShieldCheck, Users, UserCog, Inbox, UsersRound, Layers } from 'lucide-react'
import { useAuth } from '../lib/auth'
import { Alert, Loading } from '../ui'
import { Button } from '../ui'

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
  if (status === 'anon') return <Navigate to="/login" state={{ from: loc.pathname + loc.search, notice }} replace />
  if (role === 'super' && user.role !== 'super_admin') return <Navigate to="/app" replace />
  if (role === 'org' && user.role === 'super_admin') return <Navigate to="/super" replace />
  return <StaffLayout />
}

function StaffLayout() {
  const { user, org, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const loc = useLocation()
  useEffect(() => setOpen(false), [loc.pathname])
  const isSuper = user.role === 'super_admin'
  const nav = (isSuper ? SUPER_NAV : ADMIN_NAV).filter((n) => !n.admin || user.role === 'admin')

  return (
    <div className="shell">
      {open && <div className="scrim" onClick={() => setOpen(false)} />}
      <aside className={`side ${open ? 'open' : ''}`} aria-label="Main navigation">
        <Link to={isSuper ? '/super' : '/app'} className="brand"><span className="mark"><ShieldCheck size={16} /></span>ProctorAI</Link>
        {!isSuper && org && <div className="org-chip"><b>{org.name}</b><span>{org.plan_name} plan{org.status === 'trial' ? ' · trial' : ''}</span></div>}
        {isSuper && <div className="org-chip"><b>Platform console</b><span>Super admin</span></div>}
        <nav className="nav">
          {nav.map((n, i) => n.group ? <div className="nav-group" key={i}>{n.group}</div> : (
            <NavLink key={n.to} to={n.to} end={n.end}><n.icon size={17} />{n.label}</NavLink>
          ))}
        </nav>
        <div className="side-foot">
          <div className="who">{user.full_name}<span>{user.email}</span></div>
          <NavLink to="/account" className="btn ghost" style={{ marginBottom: 4 }}><Settings size={16} />Account</NavLink>
          <Button variant="ghost" icon={LogOut} onClick={logout}>Sign out</Button>
        </div>
      </aside>
      <div style={{ minWidth: 0 }}>
        <div className="topbar"><Button variant="ghost" icon={Menu} onClick={() => setOpen(true)} aria-label="Open menu" style={{ color: '#fff' }} /><b>ProctorAI</b></div>
        <main className="main">
          {!isSuper && org?.block_reason && <Alert tone="bad">{org.block_reason}</Alert>}
          {user.must_change_password && loc.pathname !== '/account' && <Alert tone="warn">You are using a temporary password. <Link to="/account">Set your own password</Link>.</Alert>}
          <Outlet />
        </main>
      </div>
    </div>
  )
}
