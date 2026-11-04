import { useState } from 'react'
import { FileArchive, FileText, Printer } from 'lucide-react'
import { api } from '../../../lib/api'
import { useAuth } from '../../../lib/auth'
import { Alert, Button, Modal, Select, useUI } from '../../../ui'

const slug = (s) => (s || 'test').replace(/[^\w]+/g, '-').replace(/^-|-$/g, '').slice(0, 50)

/* Admin dialog: every candidate's OMR sheet in one PDF, as a ZIP of single PDFs, or a blank template to print. */
export default function OmrDownloads({ test: t, onClose }) {
  const { user } = useAuth()
  const { error, toast } = useUI()
  const isAdmin = user.role === 'admin'
  const sets = t.question_sets > 1 ? 'ABCDEF'.slice(0, t.question_sets).split('') : []
  const [set, setSet] = useState('')
  const [evaluated, setEvaluated] = useState(false)
  const [live, setLive] = useState(false)
  const [busy, setBusy] = useState('')
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
  const q = (extra = {}) => new URLSearchParams(Object.entries({ tz, set, evaluated: evaluated || '', include_live: live || '', ...extra }).filter(([, v]) => v)).toString()

  async function go(kind, path, file) {
    setBusy(kind)
    try { await api.download(path, file); toast('Download started') } catch (e) { error(e) } finally { setBusy('') }
  }
  const base = `/tests/${t.id}`
  const name = slug(t.title)
  return (
    <Modal title="OMR sheets" onClose={onClose} footer={<Button onClick={onClose}>Close</Button>}>
      <div className="omr-dl">
        <p className="muted-2">Each sheet has the candidate and institute details, the test, the date and the set, with the bubbles the candidate marked.</p>
        {!t.omr_enabled && <Alert tone="info">Candidates are not shown a live OMR sheet for this test (turn it on in Settings). You can still download sheets here.</Alert>}
        {sets.length > 0 && <Select label="Question set" value={set} onChange={(e) => setSet(e.target.value)}><option value="">All sets</option>{sets.map((s) => <option key={s} value={s}>Set {s}</option>)}</Select>}
        {isAdmin && <label className="check"><input type="checkbox" checked={evaluated} onChange={(e) => setEvaluated(e.target.checked)} /><span>Evaluated copy<small>Colours right and wrong answers, rings the correct option and prints the score.</small></span></label>}
        <label className="check"><input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /><span>Include candidates who are still taking the test<small>Otherwise only submitted and ended attempts are included.</small></span></label>
        <div className="actions">
          <Button variant="primary" icon={FileText} busy={busy === 'pdf'} onClick={() => go('pdf', `${base}/omr.pdf?${q()}`, `${name}-OMR${evaluated ? '-evaluated' : ''}${set ? `-set-${set}` : ''}.pdf`)}>All sheets in one PDF</Button>
          <Button icon={FileArchive} busy={busy === 'zip'} onClick={() => go('zip', `${base}/omr.zip?${q()}`, `${name}-OMR${evaluated ? '-evaluated' : ''}${set ? `-set-${set}` : ''}.zip`)}>ZIP, one PDF each</Button>
          <Button icon={Printer} busy={busy === 'blank'} onClick={() => go('blank', `${base}/omr/blank.pdf?${q({ evaluated: '', include_live: '' })}`, `${name}-OMR-blank${set ? `-set-${set}` : ''}.pdf`)}>Blank template</Button>
        </div>
        <p className="muted-2" style={{ fontSize: 12.5 }}>Dates and times use your browser's time zone ({tz}).</p>
      </div>
    </Modal>
  )
}
