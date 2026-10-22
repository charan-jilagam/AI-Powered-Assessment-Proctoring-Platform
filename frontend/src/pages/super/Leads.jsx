import { api } from '../../lib/api'
import { ago } from '../../lib/format'
import { useDocumentTitle, usePaged } from '../../lib/hooks'
import { Badge, Empty, Loading, PageHeader, Pager, Panel, useUI } from '../../ui'

export default function Leads() {
  useDocumentTitle('Demo requests')
  const { error } = useUI()
  const list = usePaged('/superadmin/demo-requests')
  const setStatus = async (id, status) => { try { await api.patch(`/superadmin/demo-requests/${id}`, { status }); list.reload() } catch (e) { error(e) } }
  return (
    <>
      <PageHeader title="Demo requests" subtitle="People who asked for a walkthrough on the public site." />
      <Panel flush>
        {list.loading && !list.data ? <Loading /> : !list.items.length ? <Empty title="No requests yet">Requests from the landing page appear here.</Empty> : (
          <table className="t"><thead><tr><th>Who</th><th>Message</th><th>Received</th><th>Status</th></tr></thead><tbody>
            {list.items.map((r) => <tr key={r.id}><td><b>{r.name}</b><div className="sub"><a href={`mailto:${r.email}`}>{r.email}</a>{r.company ? ` · ${r.company}` : ''}{r.phone ? ` · ${r.phone}` : ''}</div></td>
              <td style={{ maxWidth: 380 }}>{r.message || <span className="muted">—</span>}</td><td className="muted nowrap">{ago(r.created_at)}</td>
              <td><select className="input" style={{ width: 'auto', height: 32 }} aria-label="Status" value={r.status} onChange={(e) => setStatus(r.id, e.target.value)}>{['new', 'contacted', 'converted', 'dismissed'].map((s) => <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>)}</select> {r.status === 'new' && <Badge status="new" />}</td></tr>)}
          </tbody></table>)}
        <Pager page={list.page} pageSize={list.pageSize} total={list.total} onPage={list.setPage} />
      </Panel>
    </>
  )
}
