// Small dependency-free SVG charts. They size to their container and keep text readable at phone width.
import { useState } from 'react'

export function BarChart({ data, height = 190, color, format = (v) => v, labelEvery = 1 }) {
  const [hover, setHover] = useState(null)
  const W = 600, pad = { l: 28, r: 6, t: 10, b: 24 }
  const max = Math.max(1, ...data.map((d) => d.value))
  const niceMax = max <= 4 ? 4 : Math.ceil(max / 4) * 4
  const bw = (W - pad.l - pad.r) / Math.max(1, data.length)
  const y = (v) => pad.t + (height - pad.t - pad.b) * (1 - v / niceMax)
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${height}`} width="100%" role="img" aria-label="Bar chart" style={{ display: 'block' }}>
      {[0, 0.5, 1].map((f) => <g key={f}><line className="grid-line" x1={pad.l} x2={W - pad.r} y1={y(niceMax * f)} y2={y(niceMax * f)} /><text x={pad.l - 6} y={y(niceMax * f) + 4} textAnchor="end">{Math.round(niceMax * f)}</text></g>)}
      {data.map((d, i) => {
        const x = pad.l + i * bw + bw * 0.14, w = bw * 0.72, h = Math.max(d.value ? 2 : 0, height - pad.b - y(d.value))
        return (
          <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <rect x={pad.l + i * bw} y={pad.t} width={bw} height={height - pad.t - pad.b} fill="transparent" />
            <rect className="bar" x={x} y={height - pad.b - h} width={w} height={h} rx="2" style={color ? { fill: color } : undefined} />
            {i % labelEvery === 0 && <text x={x + w / 2} y={height - 7} textAnchor="middle">{d.label}</text>}
            {hover === i && <g><rect x={Math.min(W - 92, Math.max(0, x + w / 2 - 46))} y={Math.max(0, height - pad.b - h - 30)} width="92" height="22" rx="4" fill="#12202b" />
              <text x={Math.min(W - 46, Math.max(46, x + w / 2))} y={Math.max(0, height - pad.b - h - 15)} textAnchor="middle" style={{ fill: '#fff' }}>{d.label}: {format(d.value)}</text></g>}
          </g>
        )
      })}
    </svg>
  )
}

export function LineChart({ data, height = 170, format = (v) => v }) {
  const W = 600, pad = { l: 28, r: 8, t: 12, b: 22 }
  const max = Math.max(1, ...data.map((d) => d.value)); const niceMax = max <= 4 ? 4 : Math.ceil(max / 4) * 4
  const x = (i) => pad.l + (W - pad.l - pad.r) * (data.length <= 1 ? 0.5 : i / (data.length - 1))
  const y = (v) => pad.t + (height - pad.t - pad.b) * (1 - v / niceMax)
  const pts = data.map((d, i) => `${x(i)},${y(d.value)}`).join(' ')
  const area = `${x(0)},${height - pad.b} ${pts} ${x(data.length - 1)},${height - pad.b}`
  const step = Math.ceil(data.length / 6)
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${height}`} width="100%" role="img" aria-label="Trend chart" style={{ display: 'block' }}>
      {[0, 0.5, 1].map((f) => <g key={f}><line className="grid-line" x1={pad.l} x2={W - pad.r} y1={y(niceMax * f)} y2={y(niceMax * f)} /><text x={pad.l - 6} y={y(niceMax * f) + 4} textAnchor="end">{Math.round(niceMax * f)}</text></g>)}
      <polygon points={area} fill="var(--accent)" opacity="0.12" />
      <polyline points={pts} fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" />
      {data.map((d, i) => <g key={i}>{i % step === 0 && <text x={x(i)} y={height - 6} textAnchor="middle">{d.label}</text>}<circle cx={x(i)} cy={y(d.value)} r="8" fill="transparent"><title>{d.label}: {format(d.value)}</title></circle></g>)}
    </svg>
  )
}

export function HBars({ items, format = (v) => v, max }) {
  const m = max ?? Math.max(1, ...items.map((i) => i.value))
  return <div>{items.map((it, i) => (
    <div className="hbar" key={i}><span className="truncate" title={it.label}>{it.label}</span><span className="track"><i style={{ width: `${Math.min(100, (it.value / m) * 100)}%`, background: it.color }} /></span><span className="v">{format(it.value)}</span></div>
  ))}</div>
}

export function StackBar({ parts }) {
  const total = parts.reduce((s, p) => s + p.value, 0) || 1
  return (
    <div>
      <div style={{ display: 'flex', height: 12, borderRadius: 6, overflow: 'hidden', background: 'var(--neutral-soft)' }} role="img" aria-label={parts.map((p) => `${p.label} ${p.value}`).join(', ')}>
        {parts.map((p, i) => p.value > 0 && <i key={i} style={{ width: `${(p.value / total) * 100}%`, background: p.color }} title={`${p.label}: ${p.value}`} />)}
      </div>
      <div className="legend mt" style={{ marginTop: 10 }}>{parts.map((p, i) => <span key={i}><i style={{ background: p.color }} />{p.label} <b>{p.value}</b></span>)}</div>
    </div>
  )
}
