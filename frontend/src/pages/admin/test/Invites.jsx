import { useRef, useState } from 'react'
import { RotateCw, Send, Trash2, Upload } from 'lucide-react'
import { api } from '../../../lib/api'
import { ago, fmtDateTime } from '../../../lib/format'
import { usePaged } from '../../../lib/hooks'
import { Alert, Badge, Button, CopyButton, Empty, IconButton, Loading, Modal, Pager, Panel, Stats, Textarea, Check_, useUI } from '../../../ui'

export default function Invites({ test: t }) {
  const { toast, error, confirm } = useUI()
  const list = usePaged(`/tests/${t.id}/invites`, { status: '' })
  const [adding, setAdding] = useState(false)
  const file = useRef(null)
  const counts = list.data?.counts || {}

  async function importCsv(f) {
    if (!f) return
    const fd = new FormData(); fd.append('file', f)
    try { const r = await api.post(`/tests/${t.id}/invites/import-csv`, fd); toast(`${r.created.length} invited${r.skipped.length ? `, ${r.skipped.length} skipped` : ''}`); list.reload() } catch (e) { error(e) }
    file.current.value = ''
  }
  return (
    <>
      {t.access_mode === 'invite' ? <Alert tone="info">This test is <b>invite only</b>: only the e-mail addresses below can join.</Alert> : <Alert tone="info">Anyone with the code can join. Invitations are optional: they e-mail a personal link and let you track who has not started.</Alert>}
      {t.status === 'draft' && <Alert tone="warn">Publish the test before candidates try their links.</Alert>}
      <Stats items={[{ value: counts.pending ?? 0, label: 'Waiting' }, { value: counts.started ?? 0, label: 'Started' }, { value: counts.completed ?? 0, label: 'Completed' }]} />
      <div className="toolbar">
        <Button variant="primary" icon={Send} onClick={() => setAdding(true)}>Invite candidates</Button>
        <input ref={file} type="file" accept=".csv,text/csv" hidden onChange={(e) => importCsv(e.target.files[0])} />
        <Button icon={Upload} onClick={() => file.current.click()}>Import CSV</Button>
        <span className="muted" style={{ fontSize: 13 }}>CSV needs an <code>email</code> column and optionally <code>name</code>.</span>
        <select className="input right" aria-label="Status" value={list.filters.status} onChange={(e) => list.setFilter('status', e.target.value)}><option value="">All</option>{['pending', 'started', 'completed', 'revoked'].map((s) => <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>)}</select>
      </div>
      <Panel flush>
        {list.loading && !list.data ? <Loading /> : !list.items.length ? <Empty title="No invitations yet">Paste e-mail addresses to send each person their own link.</Empty> : (
          <table className="t"><thead><tr><th>Candidate</th><th>Status</th><th>Sent</th><th>Expires</th><th /></tr></thead><tbody>
            {list.items.map((i) => (
              <tr key={i.id}><td><b>{i.name || i.email}</b>{i.name && <div className="sub">{i.email}</div>}</td><td><Badge status={i.status} /></td><td className="muted">{i.sent_at ? ago(i.sent_at) : 'Not e-mailed'}</td><td className="muted">{fmtDateTime(i.expires_at)}</td>
                <td className="num nowrap"><CopyButton text={i.link} label="Copy link" />{' '}
                  {i.status !== 'completed' && <IconButton icon={RotateCw} label="Resend invitation" onClick={async () => { try { await api.post(`/tests/${t.id}/invites/${i.id}/resend`); toast('Invitation sent again'); list.reload() } catch (e) { error(e) } }} />}
                  {i.status !== 'revoked' && i.status !== 'completed' && <IconButton icon={Trash2} label="Revoke invitation" onClick={async () => { if (await confirm({ title: 'Revoke this invitation?', message: `${i.email} will no longer be able to use their personal link${t.access_mode === 'invite' ? ' or join at all' : ''}.`, confirmLabel: 'Revoke', danger: true })) { try { await api.del(`/tests/${t.id}/invites/${i.id}`); list.reload() } catch (e) { error(e) } } }} />}</td></tr>))}
          </tbody></table>)}
        <Pager page={list.page} pageSize={list.pageSize} total={list.total} onPage={list.setPage} />
      </Panel>
      {adding && <InviteModal testId={t.id} onClose={() => { setAdding(false); list.reload() }} />}
    </>
  )
}

function InviteModal({ testId, onClose }) {
  const { error } = useUI()
  const [text, setText] = useState('')
  const [send, setSend] = useState(true)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(null)
  const parsed = text.split(/\n/).map((l) => l.trim()).filter(Boolean).map((l) => {
    const m = l.match(/^(.*?)[,;\t ]+([^\s,;]+@[^\s,;]+)$/) || l.match(/^()([^\s,;]+@[^\s,;]+)$/) || l.match(/^([^\s,;]+@[^\s,;]+)[,;\t ]+(.+)$/)
    if (!m) return null
    const [a, b] = [m[1].trim(), m[2].trim()]
    return a.includes('@') ? { email: a, name: b || undefined } : { email: b, name: a || undefined }
  })
  const valid = parsed.filter(Boolean)
  async function go() {
    setBusy(true)
    try { setDone(await api.post(`/tests/${testId}/invites`, { invitees: valid, send_email: send })) } catch (e) { error(e) } finally { setBusy(false) }
  }
  if (done) return <Modal title="Invitations created" onClose={onClose} footer={<Button variant="primary" onClick={onClose}>Done</Button>}>
    <Alert tone="ok">{done.created.length} invitation{done.created.length === 1 ? '' : 's'} created{send ? ' and queued for e-mail' : ''}.</Alert>
    {done.skipped.length > 0 && <Alert tone="warn">Skipped: {done.skipped.map((s) => (typeof s === 'string' ? s : `${s.email} (${s.reason})`)).join(', ')}</Alert>}
    {done.note && <Alert tone="info">{done.note}</Alert>}</Modal>
  return (
    <Modal wide title="Invite candidates" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!valid.length} busy={busy} onClick={go}>Create {valid.length || ''} invitation{valid.length === 1 ? '' : 's'}</Button></>}>
      <Textarea label="One person per line" rows={8} value={text} onChange={(e) => setText(e.target.value)} placeholder={'asha@example.com\nRavi Kumar, ravi@example.com'} hint="Either “name, email” or just the email." />
      {text && parsed.some((p) => !p) && <Alert tone="warn">{parsed.filter((p) => !p).length} line(s) have no valid e-mail and will be ignored.</Alert>}
      <Check_ label="E-mail each person their link now" hint="Without SMTP the message is stored in the platform outbox and you can copy links manually." checked={send} onChange={(e) => setSend(e.target.checked)} />
    </Modal>
  )
}
