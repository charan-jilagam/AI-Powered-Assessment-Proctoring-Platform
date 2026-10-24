import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'

// Paged + filtered list with stable state. `filters` is a plain object that becomes query params.
export function usePaged(path, initial = {}, { pageSize = 25, enabled = true } = {}) {
  const [filters, setFilters] = useState(initial)
  const [page, setPage] = useState(1)
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const seq = useRef(0)
  const load = useCallback(async () => {
    if (!enabled) return
    const mine = ++seq.current
    setState((s) => ({ ...s, loading: true }))
    try {
      const data = await api.get(path, { ...filters, page, page_size: pageSize })
      if (mine === seq.current) setState({ data, error: null, loading: false })
    } catch (error) { if (mine === seq.current) setState((s) => ({ ...s, error, loading: false })) }
  }, [path, filters, page, pageSize, enabled])
  useEffect(() => { load() }, [load])
  return {
    ...state, items: state.data?.items || [], total: state.data?.total || 0, page, pageSize, setPage, filters, reload: load,
    setFilter: (k, v) => { setPage(1); setFilters((f) => ({ ...f, [k]: v })) },
  }
}

// Calls `fn` every `ms` while the tab is visible.
export function usePoll(fn, ms, active = true) {
  const ref = useRef(fn)
  ref.current = fn
  useEffect(() => {
    if (!active) return
    const tick = () => { if (!document.hidden) ref.current() }
    const id = setInterval(tick, ms)
    return () => clearInterval(id)
  }, [ms, active])
}

export function useDocumentTitle(title) {
  useEffect(() => { document.title = title ? `${title} · ORVEXA` : 'ORVEXA' }, [title])
}
