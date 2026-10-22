import { pct } from '../../../lib/format'
import { Async, Empty, Panel, Stats, useLoad } from '../../../ui'
import { api } from '../../../lib/api'
import { BarChart, HBars, StackBar } from '../../../ui/charts'
import { Link } from 'react-router-dom'

export default function Analytics({ test: t }) {
  const state = useLoad(() => api.get(`/tests/${t.id}/analytics`), [t.id])
  return (
    <Async state={state}>{(d) => {
      const s = d.summary
      if (!s.total_attempts) return <Panel><Empty title="No data yet">Analytics appear once candidates start submitting.</Empty></Panel>
      return (
        <>
          <Stats items={[
            { value: s.submitted, label: 'Submitted', sub: `${s.terminated} terminated · ${s.in_progress} in progress` },
            { value: pct(s.average_percentage), label: 'Average score', sub: `Median ${pct(s.median_percentage)}` },
            { value: pct(s.pass_rate), label: 'Pass rate', sub: `Pass mark ${d.test.pass_percentage}%` },
            { value: s.average_time_minutes != null ? `${s.average_time_minutes} min` : '—', label: 'Average time' },
            { value: s.average_risk ?? '—', label: 'Average risk' },
          ]} />
          <div className="grid c2" style={{ alignItems: 'start' }}>
            <Panel title="Score distribution"><BarChart data={d.histogram.map((h) => ({ label: h.label.split('-')[0], value: h.count }))} format={(v) => `${v} candidate${v === 1 ? '' : 's'}`} /><p className="hint" style={{ textAlign: 'center' }}>Score band (% in steps of 10)</p></Panel>
            <Panel title="Integrity risk"><StackBar parts={[{ label: 'Low', value: d.risk_distribution.low, color: 'var(--ok)' }, { label: 'Medium', value: d.risk_distribution.medium, color: 'var(--warn)' }, { label: 'High', value: d.risk_distribution.high, color: 'var(--bad)' }]} />
              <h3 className="mt-lg" style={{ margin: '24px 0 8px' }}>Most common flags</h3>{d.violations_by_type.length ? <HBars items={d.violations_by_type.slice(0, 6).map((v) => ({ label: v.label, value: v.count }))} /> : <p className="muted">No flags raised.</p>}</Panel>
          </div>
          <Panel className="mt" title="Question difficulty (hardest first)" flush>
            <div className="table-wrap"><table className="t"><thead><tr><th>Question</th><th className="num">Shown</th><th className="num">Correct</th><th style={{ width: 180 }}>Correct rate</th><th>Most common wrong answer</th></tr></thead><tbody>
              {d.question_stats.map((q) => <tr key={q.question_id}><td style={{ maxWidth: 360 }}>{q.text}</td><td className="num">{q.shown}</td><td className="num">{q.correct}</td><td><HBars items={[{ label: '', value: q.correct_rate, color: q.correct_rate < 35 ? 'var(--bad)' : q.correct_rate < 70 ? 'var(--warn)' : 'var(--ok)' }]} max={100} format={(v) => `${v}%`} /></td><td className="muted">{q.most_common_wrong ?? '—'}</td></tr>)}
            </tbody></table></div></Panel>
          <Panel className="mt" title="Top scorers" flush><table className="t"><tbody>{d.leaderboard.map((l, i) => <tr key={l.attempt_id}><td className="num muted" style={{ width: 40 }}>{i + 1}</td><td><Link className="name" to={`/app/attempts/${l.attempt_id}`}>{l.name}</Link></td><td className="num">{l.score}/{l.max_score}</td><td className="num">{pct(l.percentage)}</td></tr>)}</tbody></table></Panel>
        </>
      )
    }}</Async>
  )
}
