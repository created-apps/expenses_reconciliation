import { createContext, useContext } from 'react'

export type AuthState = {
  status: 'loading' | 'signed-out' | 'signed-in'
  email: string | null
  /** Why the user is signed out, when it was not their choice (not allowed, server down, ...). */
  error: string | null
}

export type AuthContextValue = AuthState & {
  /** Resolves to an error message, or null when sign-in succeeded and the account is allowed. */
  signIn: (email: string, password: string) => Promise<string | null>
  signOut: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>')
  return value
}
