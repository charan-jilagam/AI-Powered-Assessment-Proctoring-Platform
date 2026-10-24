import { useEffect, useState } from 'react'
import { api } from './api'

// Debounced global search (tests + candidates of the signed-in organization).
export function useSearch(q) {
  const [res, setRes] = useState({ tests: [], candidates: [] })
  useEffect(() => {
    const term = q.trim()
    if (term.length < 2) { setRes({ tests: [], candidates: [] }); return undefined }
    let live = true
    const t = setTimeout(() => { api.get(`/org/search?q=${encodeURIComponent(term)}`).then((r) => live && setRes(r)).catch(() => {}) }, 220)
    return () => { live = false; clearTimeout(t) }
  }, [q])
  return res
}
