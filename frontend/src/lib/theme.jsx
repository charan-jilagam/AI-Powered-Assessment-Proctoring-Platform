import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { Monitor, Moon, Sun } from 'lucide-react'

// Light is the default. "system" follows the operating system and updates live.
const KEY = 'pai_theme'
const MODES = ['light', 'dark', 'system']
const Ctx = createContext({ mode: 'light', resolved: 'light', setMode: () => {} })

const read = () => { try { const v = localStorage.getItem(KEY); return MODES.includes(v) ? v : 'light' } catch { return 'light' } }
const systemDark = () => typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches
const resolve = (mode) => (mode === 'system' ? (systemDark() ? 'dark' : 'light') : mode)

function apply(resolved) {
  const root = document.documentElement
  root.setAttribute('data-theme', resolved)
  root.style.colorScheme = resolved
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', resolved === 'dark' ? '#0d161d' : '#f3f5f4')
}

export function ThemeProvider({ children }) {
  const [mode, setModeState] = useState(read)
  const [resolved, setResolved] = useState(() => resolve(read()))

  useEffect(() => {
    const update = () => { const r = resolve(mode); setResolved(r); apply(r) }
    update()
    if (mode !== 'system' || typeof matchMedia !== 'function') return
    const mq = matchMedia('(prefers-color-scheme: dark)')
    mq.addEventListener('change', update)
    return () => mq.removeEventListener('change', update)
  }, [mode])

  // keep several open tabs in sync
  useEffect(() => {
    const onStorage = (e) => { if (e.key === KEY) setModeState(read()) }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const setMode = useCallback((m) => { setModeState(m); try { localStorage.setItem(KEY, m) } catch { /* private mode */ } }, [])
  const value = useMemo(() => ({ mode, resolved, setMode }), [mode, resolved, setMode])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export const useTheme = () => useContext(Ctx)

const OPTIONS = [['light', 'Light', Sun], ['dark', 'Dark', Moon], ['system', 'Match system', Monitor]]

// Three-way switch. `onDark` styles it for the always-dark sidebar.
export function ThemeToggle({ className = '', onDark = false }) {
  const { mode, setMode } = useTheme()
  return (
    <div className={`theme-toggle ${onDark ? 'on-dark' : ''} ${className}`} role="radiogroup" aria-label="Colour theme">
      {OPTIONS.map(([id, label, Icon]) => (
        <button key={id} type="button" role="radio" aria-checked={mode === id} aria-label={label} title={label} className={mode === id ? 'on' : ''} onClick={() => setMode(id)}><Icon size={15} /></button>
      ))}
    </div>
  )
}

// A small floating switch for pages without a header (login, join, lobby). Hidden while the exam room has its own.
export function ThemeFloat() {
  const { resolved, setMode } = useTheme()
  const Icon = resolved === 'dark' ? Sun : Moon
  return (
    <button type="button" className="theme-float" aria-label={resolved === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'} title={resolved === 'dark' ? 'Light theme' : 'Dark theme'} onClick={() => setMode(resolved === 'dark' ? 'light' : 'dark')}><Icon size={17} /></button>
  )
}
