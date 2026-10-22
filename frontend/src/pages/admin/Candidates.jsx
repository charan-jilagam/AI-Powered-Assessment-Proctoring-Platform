import { api } from '../../lib/api'
import { fmtDate } from '../../lib/format'
import { useAuth } from '../../lib/auth'
import { useDocumentTitle, usePaged } from '../../lib/hooks'
import { Badge, Button, Empty, Loading, PageHeader, Pager, Panel, SearchBox, useUI } from '../../ui'

export default function Candidates() {
  useDocumentTitle('Candidates')
  const { user } = useAuth()
  const { toast, error, confirm } = useUI()
  const list = usePaged('/candidates', { q: '' })
  const isAdmin = user.role === 'admin'
  return (
    <>
      <PageHeader title="Candidates" subtitle="Everyone who has joined one of your tests." />
      <div className="toolbar"><SearchBox value={list.filters.q} onChange={(v) => list.setFilter('q', v)} placeholder="Search name or e-mail" /></div>
      <Panel flush>
        {list.loading && !list.data ? <Loading /> : !list.items.length ? <Empty title="No candidates yet" /> : (
          <table className="t"><thead><tr><th>Candidate</th><th className="num">Attempts</th><th>First seen</th><th>Access</th>{isAdmin && <th />}</tr></thead><tbody>
            {list.items.map((c) => <tr key={c.id}><td><b>{c.name}</b><div className="sub">{c.email}{c.phone ? ` · ${c.phone}` : ''}</div></td><td className="num">{c.attempts}</td><td className="muted">{fmtDate(c.created_at)}</td><td>{c.is_active ? <Badge status="active" /> : <Badge status="suspended">Blocked</Badge>}</td>
              {isAdmin && <td className="num nowrap"><Button size="sm" onClick={async () => { try { await api.patch(`/candidates/${c.id}`, { is_active: !c.is_active }); toast(c.is_active ? 'Candidate blocked' : 'Candidate unblocked'); list.reload() } catch (e) { error(e) } }}>{c.is_active ? 'Block' : 'Unblock'}</Button>{' '}
                <Button size="sm" onClick={async () => { if (await confirm({ title: 'Erase personal data?', message: `${c.name}'s name, e-mail, photos and answers' metadata are permanently removed. Scores stay as anonymous statistics. This cannot be undone.`, confirmLabel: 'Erase data', danger: true })) { try { await api.del(`/candidates/${c.id}`); toast('Personal data erased'); list.reload() } catch (e) { error(e) } } }}>Erase data</Button></td>}</tr>)}
          </tbody></table>)}
        <Pager page={list.page} pageSize={list.pageSize} total={list.total} onPage={list.setPage} />
      </Panel>
    </>
  )
}
