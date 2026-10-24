import { lazy, Suspense } from 'react'
import { Route, Routes, useLocation } from 'react-router-dom'
import { ThemeFloat } from './lib/theme'
import { RequireRole } from './layouts/StaffLayout'
import { Loading } from './ui'

const L = (loader) => lazy(loader)
const Landing = L(() => import('./pages/public/Landing'))
const Login = L(() => import('./pages/public/Login'))
const Forgot = L(() => import('./pages/public/Forgot'))
const SetPassword = L(() => import('./pages/public/SetPassword'))
const NotFound = L(() => import('./pages/public/NotFound'))
const Account = L(() => import('./pages/public/Account'))

const SuperOverview = L(() => import('./pages/super/Overview'))
const Orgs = L(() => import('./pages/super/Orgs'))
const OrgDetail = L(() => import('./pages/super/OrgDetail'))
const Plans = L(() => import('./pages/super/Plans'))
const PlatformAdmins = L(() => import('./pages/super/PlatformAdmins'))
const Leads = L(() => import('./pages/super/Leads'))
const Outbox = L(() => import('./pages/super/Outbox'))
const SuperAudit = L(() => import('./pages/super/Audit'))

const Dashboard = L(() => import('./pages/admin/Dashboard'))
const Tests = L(() => import('./pages/admin/Tests'))
const TestNew = L(() => import('./pages/admin/TestNew'))
const TestDetail = L(() => import('./pages/admin/TestDetail'))
const AttemptReport = L(() => import('./pages/admin/AttemptReport'))
const ReportPrint = L(() => import('./pages/admin/ReportPrint'))
const Bank = L(() => import('./pages/admin/Bank'))
const ReviewQueue = L(() => import('./pages/admin/ReviewQueue'))
const Candidates = L(() => import('./pages/admin/Candidates'))
const Team = L(() => import('./pages/admin/Team'))
const Integrations = L(() => import('./pages/admin/Integrations'))
const Billing = L(() => import('./pages/admin/Billing'))
const OrgAudit = L(() => import('./pages/admin/Audit'))

const Join = L(() => import('./pages/candidate/Join'))
const ExamRoom = L(() => import('./pages/candidate/ExamRoom'))

export default function App() {
  const { pathname } = useLocation()
  const staff = pathname.startsWith('/app') || pathname.startsWith('/super') || pathname === '/account' || pathname === '/'
  return (
    <Suspense fallback={<Loading />}>
      {!staff && <ThemeFloat />}
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route path="/forgot-password" element={<Forgot />} />
        <Route path="/reset-password" element={<SetPassword mode="reset" />} />
        <Route path="/accept-invite" element={<SetPassword mode="invite" />} />
        <Route path="/t/:code" element={<Join />} />
        <Route path="/exam" element={<ExamRoom />} />

        <Route element={<RequireRole role="any" />}>
          <Route path="/account" element={<Account />} />
        </Route>

        <Route path="/super" element={<RequireRole role="super" />}>
          <Route index element={<SuperOverview />} />
          <Route path="organizations" element={<Orgs />} />
          <Route path="organizations/:id" element={<OrgDetail />} />
          <Route path="plans" element={<Plans />} />
          <Route path="admins" element={<PlatformAdmins />} />
          <Route path="leads" element={<Leads />} />
          <Route path="outbox" element={<Outbox />} />
          <Route path="audit" element={<SuperAudit />} />
        </Route>

        <Route path="/app" element={<RequireRole role="org" />}>
          <Route index element={<Dashboard />} />
          <Route path="tests" element={<Tests />} />
          <Route path="tests/new" element={<TestNew />} />
          <Route path="tests/:id/*" element={<TestDetail />} />
          <Route path="attempts/:id" element={<AttemptReport />} />
          <Route path="attempts/:id/report" element={<ReportPrint />} />
          <Route path="bank" element={<Bank />} />
          <Route path="review" element={<ReviewQueue />} />
          <Route path="candidates" element={<Candidates />} />
          <Route path="team" element={<Team />} />
          <Route path="settings" element={<Integrations />} />
          <Route path="billing" element={<Billing />} />
          <Route path="audit" element={<OrgAudit />} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  )
}
