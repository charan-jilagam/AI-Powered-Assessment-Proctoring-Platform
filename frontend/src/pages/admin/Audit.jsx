import { useDocumentTitle, usePaged } from '../../lib/hooks'
import { PageHeader, SearchBox } from '../../ui'
import { AuditTable } from '../super/Audit'

export default function OrgAudit() {
  useDocumentTitle('Audit log')
  const list = usePaged('/org/audit-log', { action: '' }, { pageSize: 50 })
  return (<><PageHeader title="Audit log" subtitle="Who did what in your organization: sign-ins, test changes, reviews, exports." />
    <div className="toolbar"><SearchBox value={list.filters.action} onChange={(v) => list.setFilter('action', v)} placeholder="Filter by action, e.g. TEST_PUBLISHED" /></div>
    <AuditTable list={list} /></>)
}
