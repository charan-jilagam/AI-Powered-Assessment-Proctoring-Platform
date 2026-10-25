import { useState } from 'react'
import { Plus, Trash2, Zap } from 'lucide-react'
import { api } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { ago, fmtDateTime } from '../../lib/format'
import { useDocumentTitle } from '../../lib/hooks'
import { Alert, Async, Badge, Button, Check_, CopyButton, Empty, IconButton, Input, Modal, PageHeader, Panel, Tabs, useLoad, useUI } from '../../ui'

export default function Integrations() {
  useDocumentTitle('Integrations')
  const [tab, setTab] = useState('brand')
  const { feature } = useAuth()
  return (
    <>
      <PageHeader title="Integrations & branding" subtitle="Make candidate pages look like yours and connect results to your other systems." />
      <Tabs active={tab} onChange={setTab} tabs={[{ id: 'brand', label: 'Branding' }, { id: 'keys', label: 'API keys' }, { id: 'hooks', label: 'Webhooks' }]} />
      {tab === 'brand' && <Brand />}
      {tab === 'keys' && (feature('api_access') ? <Keys /> : <Alert tone="warn">API access is not included in your plan.</Alert>)}
      {tab === 'hooks' && (feature('webhooks_enabled') ? <Hooks /> : <Alert tone="warn">Webhooks are not included in your plan.</Alert>)}
    </>
  )
}

function Brand() {
  const { org, refresh } = useAuth()
  const { toast, error } = useUI()
  const [f, setF] = useState({ name: org.name, brand_color: org.brand_color || '#0f766e', logo_url: org.logo_url || '', candidate_data_retention_days: org.candidate_data_retention_days ?? 365, candidate_domain_lock: !!org.candidate_domain_lock })
  const [busy, setBusy] = useState(false)
  async function save() {
    setBusy(true)
    try { await api.patch('/org', { name: f.name, brand_color: f.brand_color, logo_url: f.logo_url || null, candidate_data_retention_days: Number(f.candidate_data_retention_days), ...(org.allowed_domains?.length ? { candidate_domain_lock: f.candidate_domain_lock } : {}) }); await refresh(); toast('Saved') } catch (e) { error(e) } finally { setBusy(false) }
  }
  return (
    <div className="grid c2" style={{ alignItems: 'start' }}>
      <Panel title="Organization">
        <Input label="Name shown to candidates" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <div className="grid c2"><Input label="Brand color" type="color" value={f.brand_color} onChange={(e) => setF({ ...f, brand_color: e.target.value })} style={{ padding: 3 }} /><Input label="Keep candidate data (days)" type="number" min="30" value={f.candidate_data_retention_days} onChange={(e) => setF({ ...f, candidate_data_retention_days: e.target.value })} /></div>
        <Input label="Logo URL" type="url" placeholder="https://…/logo.png" value={f.logo_url} onChange={(e) => setF({ ...f, logo_url: e.target.value })} hint="Public https address of a square or wide logo." />
        <h3 className="mt">E-mail domains</h3>
        {org.allowed_domains?.length ? <>
          <div className="chips mb">{org.allowed_domains.map((d) => <span key={d} className="chip">@{d}</span>)}</div>
          <Check_ label="Only let candidates with these e-mail domains join our tests" checked={f.candidate_domain_lock} onChange={(e) => setF({ ...f, candidate_domain_lock: e.target.checked })} />
          <p className="hint mb">Your team members must always use these domains. Ask the platform owner to change the list.</p>
        </> : <p className="hint mb">No domain restriction is set for your organization. Ask the platform owner to add your company domains (for example <code>yourcompany.com</code>).</p>}
        <Button variant="primary" busy={busy} onClick={save}>Save</Button>
      </Panel>
      <Panel title="What candidates see">
        <div style={{ border: '1px solid var(--line)', borderRadius: 10, padding: 22, textAlign: 'center' }}>
          {f.logo_url ? <img src={f.logo_url} alt="" style={{ maxHeight: 44, maxWidth: 180 }} onError={(e) => { e.currentTarget.style.display = 'none' }} /> : <b style={{ fontFamily: 'var(--font-display)', fontSize: '1.3rem' }}>{f.name}</b>}
          <p className="muted" style={{ margin: '6px 0 14px' }}>You have been invited to take a test</p>
          <span className="btn primary" style={{ background: f.brand_color, borderColor: f.brand_color, color: '#fff', pointerEvents: 'none' }}>Continue</span>
        </div>
      </Panel>
    </div>
  )
}

function Keys() {
  const { toast, error, confirm } = useUI()
  const state = useLoad(() => api.get('/org/api-keys'), [])
  const [name, setName] = useState('')
  const [made, setMade] = useState(null)
  return (
    <>
      <Panel title="API keys" actions={<form className="row" onSubmit={async (e) => { e.preventDefault(); try { setMade(await api.post('/org/api-keys', { name })); setName(''); state.reload() } catch (x) { error(x) } }}><input className="input" aria-label="Key name" placeholder="Name, e.g. HR system" value={name} onChange={(e) => setName(e.target.value)} minLength={2} required /><Button type="submit" variant="primary" icon={Plus}>Create key</Button></form>} flush>
        <Async state={state}>{(rows) => !rows.length ? <Empty title="No keys yet">Send the key in an <code>X-API-Key</code> header to call the same endpoints this app uses, scoped to your organization.</Empty> : (
          <table className="t"><thead><tr><th>Name</th><th>Key</th><th>Last used</th><th /></tr></thead><tbody>{rows.map((k) => <tr key={k.id} style={{ opacity: k.revoked ? 0.5 : 1 }}><td><b>{k.name}</b>{k.revoked && <> <Badge status="revoked" /></>}</td><td><code>{k.key_prefix}…</code></td><td className="muted">{k.last_used_at ? ago(k.last_used_at) : 'Never'}</td><td className="num">{!k.revoked && <IconButton icon={Trash2} label="Revoke key" onClick={async () => { if (await confirm({ title: `Revoke “${k.name}”?`, message: 'Anything using this key stops working immediately.', confirmLabel: 'Revoke', danger: true })) { try { await api.del(`/org/api-keys/${k.id}`); toast('Key revoked'); state.reload() } catch (e) { error(e) } } }} />}</td></tr>)}</tbody></table>)}</Async>
      </Panel>
      {made && <Modal title="Copy your new key" onClose={() => setMade(null)} footer={<Button variant="primary" onClick={() => setMade(null)}>I have copied it</Button>}>
        <Alert tone="warn">{made.notice}</Alert><div className="row"><input className="input mono grow" readOnly value={made.key} onFocus={(e) => e.target.select()} aria-label="API key" /><CopyButton text={made.key} /></div></Modal>}
    </>
  )
}

function Hooks() {
  const { toast, error, confirm } = useUI()
  const state = useLoad(() => api.get('/org/webhooks'), [])
  const events = useLoad(() => api.get('/org/webhooks/events'), [])
  const [edit, setEdit] = useState(null)
  const [secret, setSecret] = useState(null)
  const [log, setLog] = useState(null)
  return (
    <>
      <Panel title="Webhook endpoints" actions={<Button variant="primary" icon={Plus} onClick={() => setEdit({ url: '', events: [], is_active: true })}>Add endpoint</Button>} flush>
        <Async state={state}>{(rows) => !rows.length ? <Empty title="No endpoints">We POST a signed JSON event to your URL when candidates start, submit or finish a test. Verify the <code>X-Orvexa-Signature</code> header with your signing secret.</Empty> : (
          <table className="t"><tbody>{rows.map((h) => <tr key={h.id}><td><b className="mono" style={{ wordBreak: 'break-all' }}>{h.url}</b><div className="sub">{h.events.length ? h.events.join(', ') : 'All events'} · secret {h.secret_hint}</div></td><td>{h.is_active ? <Badge status="active" /> : <Badge>Paused</Badge>}</td>
            <td className="num nowrap"><Button size="sm" icon={Zap} onClick={async () => { try { await api.post(`/org/webhooks/${h.id}/test`); toast('Test event sent'); } catch (e) { error(e) } }}>Send test</Button>{' '}<Button size="sm" onClick={() => setLog(h)}>Deliveries</Button>{' '}<Button size="sm" onClick={() => setEdit(h)}>Edit</Button>{' '}
              <IconButton icon={Trash2} label="Delete endpoint" onClick={async () => { if (await confirm({ title: 'Delete this endpoint?', message: h.url, confirmLabel: 'Delete', danger: true })) { try { await api.del(`/org/webhooks/${h.id}`); state.reload() } catch (e) { error(e) } } }} /></td></tr>)}</tbody></table>)}</Async>
      </Panel>
      {edit && <HookEditor hook={edit} events={events.data || []} onClose={() => setEdit(null)} onSaved={(r) => { setEdit(null); state.reload(); if (r?.secret) setSecret(r) }} />}
      {secret && <Modal title="Signing secret" onClose={() => setSecret(null)} footer={<Button variant="primary" onClick={() => setSecret(null)}>Done</Button>}><Alert tone="warn">Copy the secret now — it is shown only once.</Alert><div className="row"><input className="input mono grow" readOnly value={secret.secret} onFocus={(e) => e.target.select()} aria-label="Signing secret" /><CopyButton text={secret.secret} /></div></Modal>}
      {log && <Deliveries hook={log} onClose={() => setLog(null)} />}
    </>
  )
}

function HookEditor({ hook, events, onClose, onSaved }) {
  const { error } = useUI()
  const [f, setF] = useState({ url: hook.url, events: hook.events || [], is_active: hook.is_active })
  const [busy, setBusy] = useState(false)
  const toggle = (e) => setF((p) => ({ ...p, events: p.events.includes(e) ? p.events.filter((x) => x !== e) : [...p.events, e] }))
  async function save() {
    setBusy(true)
    try { const r = hook.id ? await api.put(`/org/webhooks/${hook.id}`, f) : await api.post('/org/webhooks', f); onSaved(r) } catch (e) { error(e); setBusy(false) }
  }
  return (
    <Modal title={hook.id ? 'Edit endpoint' : 'Add endpoint'} onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} onClick={save}>Save</Button></>}>
      <Input label="Endpoint URL" type="url" placeholder="https://example.com/hooks/orvexa" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} hint="Must be a public https address." />
      <div className="field"><span className="label">Events</span><p className="hint">Choose none to receive everything.</p>{events.map((e) => <Check_ key={e} label={<code>{e}</code>} checked={f.events.includes(e)} onChange={() => toggle(e)} />)}</div>
      <Check_ label="Active" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} />
    </Modal>
  )
}

function Deliveries({ hook, onClose }) {
  const state = useLoad(() => api.get(`/org/webhooks/${hook.id}/deliveries`, { page_size: 30 }), [hook.id])
  return <Modal wide title="Recent deliveries" onClose={onClose}><Async state={state}>{(d) => !d.items.length ? <p className="muted">Nothing sent yet.</p> : <table className="t"><thead><tr><th>Event</th><th>Result</th><th>Tries</th><th>When</th></tr></thead><tbody>{d.items.map((x) => <tr key={x.id}><td><code>{x.event}</code></td><td>{x.success ? <Badge status="sent">Delivered</Badge> : <Badge status="failed">{x.error || 'Failed'}</Badge>}</td><td>{x.attempts}</td><td className="muted">{fmtDateTime(x.created_at)}</td></tr>)}</tbody></table>}</Async></Modal>
}
