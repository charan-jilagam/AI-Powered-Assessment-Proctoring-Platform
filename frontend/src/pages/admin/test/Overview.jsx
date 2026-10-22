import { Link } from 'react-router-dom'
import { Check, Circle } from 'lucide-react'
import { fmtDateTime } from '../../../lib/format'
import { Alert, CopyButton, Panel, Stats } from '../../../ui'

export default function Overview({ test: t, isAdmin }) {
  const hasContent = t.question_count + t.coding_problem_count > 0
  const steps = [
    { done: hasContent, text: 'Add questions or coding problems', to: 'questions' },
    { done: !!t.instructions, text: 'Write instructions for candidates (optional)', to: 'settings', optional: true },
    { done: t.status !== 'draft', text: 'Publish the test', to: null },
    { done: t.attempts_total > 0, text: 'Share the code or send invitations', to: 'invites' },
  ]
  const share = `Your test "${t.title}" is open. Go to ${t.join_url} or enter the code ${t.code_display} at ${window.location.origin}.\nDuration: ${t.duration_minutes} minutes.${t.end_time ? `\nStart before ${fmtDateTime(t.end_time)}.` : ''}`
  return (
    <>
      <Stats items={[
        { value: t.attempts.registered, label: 'In lobby' }, { value: t.attempts.in_progress, label: 'Taking it now' },
        { value: t.attempts.submitted, label: 'Submitted' }, { value: t.attempts.terminated, label: 'Terminated' }, { value: t.total_marks, label: 'Total marks', sub: `Pass at ${t.pass_percentage}%` },
      ]} />
      {t.status === 'draft' && <Alert tone="info">This test is a draft. Candidates cannot join until you publish it.</Alert>}
      <div className="grid c2" style={{ alignItems: 'start' }}>
        {isAdmin && t.status === 'draft' && (
          <Panel title="Before you publish"><ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: 12 }}>
            {steps.map((s) => <li key={s.text} className="row" style={{ alignItems: 'flex-start' }}>{s.done ? <Check size={18} color="var(--ok)" /> : <Circle size={18} color="var(--line-strong)" />}<span style={{ color: s.done ? 'var(--text-3)' : undefined }}>{s.to && !s.done ? <Link to={`/app/tests/${t.id}/${s.to}`}>{s.text}</Link> : s.text}</span></li>)}
          </ul></Panel>
        )}
        <Panel title="How candidates get in" actions={<CopyButton text={share} label="Copy message" />}>
          <dl className="kv">
            <dt>Test code</dt><dd><code style={{ fontSize: '1.05rem', letterSpacing: '0.12em' }}>{t.code_display}</code></dd>
            <dt>Direct link</dt><dd><a href={t.join_url}>{t.join_url}</a></dd>
            <dt>Access</dt><dd>{t.access_mode === 'invite' ? 'Invite only — only invited e-mail addresses can join' : 'Anyone with the code'}{t.has_password ? ' + access password' : ''}</dd>
            <dt>Available</dt><dd>{t.start_time || t.end_time ? `${fmtDateTime(t.start_time)} → ${fmtDateTime(t.end_time)}` : 'Whenever the test is published'}</dd>
            <dt>Duration</dt><dd>{t.duration_minutes} minutes{t.questions_per_attempt ? ` · ${t.questions_per_attempt} questions drawn per candidate` : ''}</dd>
          </dl>
        </Panel>
        <Panel title="Proctoring">
          <div className="chips">
            {[['webcam_required', 'Webcam'], ['microphone_required', 'Microphone'], ['fullscreen_required', 'Fullscreen'], ['ai_monitoring', 'AI face checks'], ['id_verification', 'ID check'], ['detect_tab_switch', 'Tab-switch alerts'], ['block_copy_paste', 'Copy/paste blocked'], ['auto_terminate', `Auto-end after ${t.proctoring.max_level2_violations} serious flags`]].filter(([k]) => t.proctoring[k]).map(([k, l]) => <span className="chip" key={k}>{l}</span>)}
            {!Object.values(t.proctoring).some(Boolean) && <span className="muted">No proctoring enabled.</span>}
          </div>
          {isAdmin && <p className="mt" style={{ fontSize: 13 }}><Link to={`/app/tests/${t.id}/settings`}>Change proctoring settings</Link></p>}
        </Panel>
      </div>
    </>
  )
}
