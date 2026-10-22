import { fmtDateTime } from '../../lib/format'
import { useDocumentTitle, usePaged } from '../../lib/hooks'
import { Empty, Loading, PageHeader, Pager, Panel, SearchBox } from '../../ui'

export function AuditTable({ list, showOrg }) {
  return (
    <Panel flush>
      {list.loading && !list.data ? <Loading /> : !list.items.length ? <Empty title="No events match" /> : (
        <div className="table-wrap"><table className="t"><thead><tr><th>When</th><th>Action</th><th>Who</th>{showOrg && <th>Org</th>}<th>Details</th><th>IP</th></tr></thead><tbody>
          {list.items.map((a) => <tr key={a.id}><td className="muted nowrap">{fmtDateTime(a.created_at)}</td><td><code>{a.action}</code></td><td>{a.actor_email || <span className="muted">system</span>}</td>{showOrg && <td className="muted">{a.org_id ?? '—'}</td>}<td style={{ maxWidth: 360 }}>{a.details}</td><td className="muted">{a.ip_address}</td></tr>)}
        </tbody></table></div>)}
      <Pager page={list.page} pageSize={list.pageSize} total={list.total} onPage={list.setPage} />
    </Panel>
  )
}
export default function SuperAudit() {
  useDocumentTitle('Audit log')
  const list = usePaged('/superadmin/audit-log', { q: '', action: '' }, { pageSize: 50 })
  return (<><PageHeader title="Audit log" subtitle="Security-relevant events across the whole platform." />
    <div className="toolbar"><SearchBox value={list.filters.q} onChange={(v) => list.setFilter('q', v)} placeholder="Search actor or details" /><SearchBox value={list.filters.action} onChange={(v) => list.setFilter('action', v)} placeholder="Filter by action, e.g. LOGIN" /></div>
    <AuditTable list={list} showOrg /></>)
}
