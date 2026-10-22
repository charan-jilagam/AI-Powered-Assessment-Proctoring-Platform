import { useState } from 'react'
import { fmtDateTime } from '../../lib/format'
import { useDocumentTitle, usePaged } from '../../lib/hooks'
import { Alert, Badge, Empty, Loading, Modal, PageHeader, Pager, Panel } from '../../ui'

export default function Outbox() {
  useDocumentTitle('E-mail outbox')
  const list = usePaged('/superadmin/outbox')
  const [view, setView] = useState(null)
  return (
    <>
      <PageHeader title="E-mail outbox" subtitle="Every message the platform sends. Without SMTP configured, messages are only recorded here." />
      {list.items.some((e) => e.status === 'logged') && <Alert tone="info">Some messages are marked <b>Logged</b>: SMTP is not configured, so nothing was delivered. Set <code>SMTP_HOST</code> to send real e-mail.</Alert>}
      <Panel flush>
        {list.loading && !list.data ? <Loading /> : !list.items.length ? <Empty title="Nothing sent yet" /> : (
          <table className="t"><thead><tr><th>To</th><th>Subject</th><th>Status</th><th>When</th></tr></thead><tbody>
            {list.items.map((e) => <tr key={e.id} className="click" onClick={() => setView(e)}><td>{e.to_email}</td><td>{e.subject}</td><td><Badge status={e.status} />{e.error && <div className="sub" style={{ color: 'var(--bad)' }}>{e.error}</div>}</td><td className="muted nowrap">{fmtDateTime(e.created_at)}</td></tr>)}
          </tbody></table>)}
        <Pager page={list.page} pageSize={list.pageSize} total={list.total} onPage={list.setPage} />
      </Panel>
      {view && <Modal wide title={view.subject} onClose={() => setView(null)}><p className="muted mb">To {view.to_email}</p><iframe title="E-mail preview" sandbox="" srcDoc={view.body_html} style={{ width: '100%', height: 360, border: '1px solid var(--line)', borderRadius: 6, background: '#fff' }} /></Modal>}
    </>
  )
}
