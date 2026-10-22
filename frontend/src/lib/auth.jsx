import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api, setStaffExpiredHandler, staffToken } from './api'

const AuthCtx = createContext(null)
export const useAuth = () => useContext(AuthCtx)

export const homeFor = (user) => (user?.role === 'super_admin' ? '/super' : '/app')

export function AuthProvider({ children }) {
  const [state, setState] = useState({ status: staffToken.get() ? 'loading' : 'anon', user: null, org: null, notice: '' })

  const clear = useCallback((notice = '') => { staffToken.clear(); setState({ status: 'anon', user: null, org: null, notice }) }, [])
  useEffect(() => setStaffExpiredHandler((msg) => clear(msg || 'Your session ended. Sign in again.')), [clear])

  useEffect(() => {
    if (!staffToken.get()) return
    api.get('/auth/me').then((r) => setState({ status: 'ready', user: r.user, org: r.organization, notice: '' })).catch(() => clear())
  }, [clear])

  const value = useMemo(() => ({
    ...state,
    async login(email, password) {
      const r = await api.post('/auth/login', { email, password }, { as: 'none' })
      staffToken.set(r.access_token)
      setState({ status: 'ready', user: r.user, org: r.organization, notice: '' })
      return r.user
    },
    async refresh() {
      const r = await api.get('/auth/me')
      setState((s) => ({ ...s, user: r.user, org: r.organization }))
    },
    logout: () => clear(),
    async logoutEverywhere() { await api.post('/auth/logout-all'); clear() },
    isAdmin: state.user?.role === 'admin',
    feature: (name) => !!state.org?.features?.[name],
  }), [state, clear])

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>
}
