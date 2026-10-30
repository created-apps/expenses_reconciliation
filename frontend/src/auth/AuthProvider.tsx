import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { AuthContext, type AuthState } from '@/auth/context'
import { ApiError, apiFetch } from '@/lib/api'
import { SUPABASE_NOT_CONFIGURED, supabase } from '@/lib/supabase'

export const NOT_ALLOWED_MESSAGE = 'Your account is not allowed to use this app'

type AccountCheck =
  | { ok: true; email: string }
  | { ok: false; error: string; dropSession: boolean }

/** Asks the backend who we are. The backend is the authority on the allow-list. */
async function checkAccount(): Promise<AccountCheck> {
  try {
    const me = await apiFetch<{ email: string }>('/api/me')
    return { ok: true, email: me.email }
  } catch (e) {
    if (e instanceof ApiError) {
      if (e.status === 403) return { ok: false, error: NOT_ALLOWED_MESSAGE, dropSession: true }
      if (e.status === 401) {
        return { ok: false, error: 'Your session could not be verified. Please sign in again.', dropSession: true }
      }
      // Server down or misconfigured: keep the session so a reload can recover.
      return { ok: false, error: e.message, dropSession: false }
    }
    return { ok: false, error: 'Something went wrong. Please try again.', dropSession: false }
  }
}

const signedOut = (error: string | null = null): AuthState => ({ status: 'signed-out', email: null, error })

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading', email: null, error: null })

  useEffect(() => {
    if (!supabase) {
      setState(signedOut(SUPABASE_NOT_CONFIGURED))
      return
    }
    const client = supabase
    let active = true

    // Restore a stored session (page reload) and re-check it with the backend.
    void client.auth.getSession().then(async ({ data }) => {
      if (!active) return
      if (!data.session) {
        setState(signedOut())
        return
      }
      const check = await checkAccount()
      if (!active) return
      if (check.ok) {
        setState({ status: 'signed-in', email: check.email, error: null })
        return
      }
      // 'local' scope: only this browser. The Supabase project is shared with other apps,
      // so we must not revoke the user's sessions elsewhere.
      if (check.dropSession) await client.auth.signOut({ scope: 'local' })
      if (active) setState(signedOut(check.error))
    })

    // Keep this callback synchronous (supabase-js can deadlock on awaited calls in here).
    const { data: listener } = client.auth.onAuthStateChange((event) => {
      if (event === 'SIGNED_OUT') setState((s) => (s.status === 'signed-out' ? s : signedOut()))
    })

    return () => {
      active = false
      listener.subscription.unsubscribe()
    }
  }, [])

  const signIn = useCallback(async (email: string, password: string): Promise<string | null> => {
    if (!supabase) return SUPABASE_NOT_CONFIGURED
    const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password })
    if (error) {
      return error.message === 'Invalid login credentials' ? 'Incorrect email or password.' : error.message
    }
    const check = await checkAccount()
    if (!check.ok) {
      if (check.dropSession) await supabase.auth.signOut({ scope: 'local' })
      setState(signedOut(check.error))
      return check.error
    }
    setState({ status: 'signed-in', email: check.email, error: null })
    return null
  }, [])

  const signOut = useCallback(async () => {
    if (supabase) await supabase.auth.signOut({ scope: 'local' })
    setState(signedOut())
  }, [])

  const value = useMemo(() => ({ ...state, signIn, signOut }), [state, signIn, signOut])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
