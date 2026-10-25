import { useEffect, useRef, useState } from 'react'
import { Play, Send } from 'lucide-react'
import { cand } from '../../lib/api'
import { Alert, Badge, Button } from '../../ui'

import { isStarter, starter } from './codeTemplates'

export default function CodingPanel({ problems, attemptId }) {
  const [langs, setLangs] = useState([{ id: 71, name: 'Python', family: 'python' }])
  const [active, setActive] = useState(problems[0]?.id)
  const [drafts, setDrafts] = useState({})
  const [results, setResults] = useState({})
  const [best, setBest] = useState({})
  const [custom, setCustom] = useState({})
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const gutter = useRef(null)
  const key = (pid) => `pai_code_${attemptId}_${pid}`
  const store = useRef({ get: (k) => { try { return JSON.parse(sessionStorage.getItem(k)) } catch { return null } }, set: (k, v) => { try { sessionStorage.setItem(k, JSON.stringify(v)) } catch { /* ignore */ } } })

  useEffect(() => {
    let live = true
    ;(async () => {
      try { const l = await cand.get('/attempt/coding/languages'); if (live && l.length) setLangs(l) } catch { /* keep default */ }
      try {
        const prog = await cand.get('/attempt/coding/progress'); if (!live) return
        const d = {}, b = {}
        prog.forEach((p) => { d[p.problem_id] = { lang: p.last_language_id, code: p.last_source_code }; b[p.problem_id] = { passed: p.best_passed, total: p.best_total, verdict: p.best_verdict } })
        problems.forEach((p) => { const local = store.current.get(key(p.id)); if (local) d[p.id] = local })
        setDrafts((x) => ({ ...d, ...x })); setBest(b)
      } catch { /* first visit */ }
    })()
    return () => { live = false }
  }, []) // eslint-disable-line

  const problem = problems.find((p) => p.id === active)
  if (!problem) return <p className="muted">No coding problems.</p>
  const pyFirst = langs.find((l) => l.family === 'python') || langs[0]
  const langOf = (id) => langs.find((l) => l.id === id)
  const draft = drafts[active] || { lang: pyFirst.id, code: starter(pyFirst) }
  const update = (patch) => { const n = { ...draft, ...patch }; setDrafts((d) => ({ ...d, [active]: n })); store.current.set(key(active), n) }
  const changeLang = (id) => update({ lang: id, code: !draft.code?.trim() || isStarter(draft.code) ? starter(langOf(id)) : draft.code })
  const res = results[active]

  async function go(kind) {
    setBusy(kind); setErr('')
    try {
      const useCustom = kind === 'run' && custom[active]?.on
      const body = { language_id: draft.lang, source_code: draft.code }
      if (useCustom) body.custom_input = custom[active].text || ''
      const r = await cand.post(`/attempt/coding/${problem.id}/${kind}`, body)
      setResults((x) => ({ ...x, [active]: { ...r, kind } }))
      if (kind === 'submit') setBest((b) => ({ ...b, [active]: { passed: r.best_passed, total: r.best_total, verdict: r.verdict } }))
    } catch (e) { setErr(e.message) } finally { setBusy('') }
  }
  const onKey = (e) => {
    const t = e.target, code = draft.code ?? ''
    const set = (value, caret) => { update({ code: value }); requestAnimationFrame(() => { t.selectionStart = t.selectionEnd = caret }) }
    if (e.key === 'Tab') { e.preventDefault(); const s = t.selectionStart; set(code.slice(0, s) + '    ' + code.slice(t.selectionEnd), s + 4) }
    else if (e.key === 'Enter' && t.selectionStart === t.selectionEnd) {      // keep the indentation of the current line; indent after an opening bracket or colon
      e.preventDefault()
      const s = t.selectionStart, lineStart = code.lastIndexOf('\n', s - 1) + 1
      const line = code.slice(lineStart, s), indent = /^[ \t]*/.exec(line)[0]
      const extra = /[{(\[:]\s*$/.test(line) ? '    ' : ''
      set(code.slice(0, s) + '\n' + indent + extra + code.slice(s), s + 1 + indent.length + extra.length)
    }
  }
  const text = draft.code ?? starter(langOf(draft.lang)) ?? ''
  const lines = text.split('\n').length

  return (
    <div className="coding">
      {problems.length > 1 && <div className="tabs">{problems.map((p, i) => <button key={p.id} className={p.id === active ? 'active' : ''} onClick={() => { setActive(p.id); setErr('') }}>{i + 1}. {p.title}{best[p.id] && <Badge tone={best[p.id].passed === best[p.id].total ? 'ok' : 'warn'}>{best[p.id].passed}/{best[p.id].total}</Badge>}</button>)}</div>}
      <div className="coding-grid">
        <div className="coding-statement">
          <h2>{problem.title}</h2><p className="muted" style={{ fontSize: 13 }}>{problem.points} points · {problem.time_limit_seconds}s · {problem.memory_limit_mb} MB</p>
          <div style={{ whiteSpace: 'pre-wrap', margin: '12px 0' }}>{problem.statement}</div>
          {problem.input_format && <><h3>Input</h3><p style={{ whiteSpace: 'pre-wrap' }}>{problem.input_format}</p></>}
          {problem.output_format && <><h3>Output</h3><p style={{ whiteSpace: 'pre-wrap' }}>{problem.output_format}</p></>}
          {problem.constraints && <><h3>Constraints</h3><p style={{ whiteSpace: 'pre-wrap' }}>{problem.constraints}</p></>}
          {problem.samples.map((s, i) => <div key={i} className="sample"><b>Sample {i + 1}</b><div className="grid c2"><div><span className="hint">Input</span><pre>{s.input}</pre></div><div><span className="hint">Output</span><pre>{s.expected_output}</pre></div></div></div>)}
          {problem.hidden_test_count > 0 && <p className="hint">Your submission is also checked against {problem.hidden_test_count} hidden test{problem.hidden_test_count > 1 ? 's' : ''}.</p>}
        </div>
        <div className="coding-editor">
          <div className="row between mb"><select className="input" style={{ width: 'auto' }} aria-label="Language" value={draft.lang} onChange={(e) => changeLang(Number(e.target.value))}>{langs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select>
            <span className="row"><Button icon={Play} busy={busy === 'run'} disabled={!!busy} onClick={() => go('run')}>Run</Button><Button variant="primary" icon={Send} busy={busy === 'submit'} disabled={!!busy} onClick={() => go('submit')}>Submit</Button></span></div>
          <div className="code-frame"><pre className="gutter" ref={gutter} aria-hidden>{Array.from({ length: lines }, (_, n) => n + 1).join('\n')}</pre><textarea className="code-area" aria-label="Code editor" spellCheck={false} wrap="off" autoCapitalize="off" autoCorrect="off" value={text} onChange={(e) => update({ code: e.target.value })} onKeyDown={onKey} onScroll={(e) => { if (gutter.current) gutter.current.scrollTop = e.target.scrollTop }} /></div>
          <label className="check" style={{ margin: '8px 0' }}><input type="checkbox" checked={!!custom[active]?.on} onChange={(e) => setCustom({ ...custom, [active]: { ...custom[active], on: e.target.checked } })} />Run with my own input</label>
          {custom[active]?.on && <textarea className="input mono" rows={3} aria-label="Custom input" value={custom[active].text || ''} onChange={(e) => setCustom({ ...custom, [active]: { ...custom[active], text: e.target.value } })} />}
          {err && <Alert tone="bad" className="mt">{err}</Alert>}
          {res && <Result res={res} />}
        </div>
      </div>
    </div>
  )
}

function Result({ res }) {
  if (res.mode === 'custom') return <div className="coding-result"><b>Output</b><pre>{res.stdout || '(no output)'}</pre>{(res.stderr || res.compile_output) && <pre className="bad">{res.compile_output || res.stderr}</pre>}</div>
  const ok = res.verdict === 'Accepted'
  return (
    <div className="coding-result">
      <div className="row between"><b>{res.kind === 'submit' ? 'Submission' : 'Sample run'}: <span style={{ color: ok ? 'var(--ok)' : 'var(--bad)' }}>{res.verdict}</span></b><span>{res.passed}/{res.total} passed</span></div>
      {res.compile_output && <pre className="bad">{res.compile_output}</pre>}
      {res.cases.map((c, i) => (
        <details key={i} className="case" open={!c.passed && c.is_sample}><summary><Badge tone={c.passed ? 'ok' : 'bad'}>{c.passed ? 'Pass' : 'Fail'}</Badge> {c.label} <span className="muted">{c.verdict}</span></summary>
          {c.is_sample && <div className="grid c2"><div><span className="hint">Expected</span><pre>{c.expected_output}</pre></div><div><span className="hint">Your output</span><pre>{c.actual_output}</pre></div>{c.stderr && <pre className="bad" style={{ gridColumn: '1/-1' }}>{c.stderr}</pre>}</div>}</details>))}
    </div>
  )
}
