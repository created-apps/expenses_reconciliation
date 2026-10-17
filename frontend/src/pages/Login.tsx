import { useState, type FormEvent } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { useAuth } from '@/auth/context'
import { Button } from '@/components/ui/button'

const inputClass =
  'mt-1 h-9 w-full rounded border border-stone-200 bg-white px-2 text-[12px] outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100'

export default function Login() {
  const { status, error: authError, signIn } = useAuth()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  if (status === 'signed-in') {
    const from = (location.state as { from?: string } | null)?.from
    return <Navigate to={from && from !== '/login' ? from : '/'} replace />
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setFormError(null)
    const message = await signIn(email, password)
    setSubmitting(false)
    if (message) setFormError(message)
  }

  const error = formError ?? authError

  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-[#fafaf9] px-4 py-8">
      <div className="w-full max-w-[380px] rounded-md border border-stone-200 bg-white p-6">
        <p className="text-[15px] font-semibold tracking-tight text-stone-900">Reconcile</p>
        <h1 className="mt-2 text-[22px] font-semibold tracking-[-0.02em] text-stone-900">Sign in</h1>
        <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-4">
          <label className="text-[12px] font-medium text-stone-700">
            Email
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={inputClass}
            />
          </label>
          <label className="text-[12px] font-medium text-stone-700">
            Password
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputClass}
            />
          </label>
          <Button type="submit" className="w-full" disabled={submitting || status === 'loading'}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </Button>
          {error && (
            <p role="alert" className="text-[12px] text-red-700">
              {error}
            </p>
          )}
        </form>
      </div>
      <p className="mt-4 text-[12px] text-stone-500">Accounts are created by your administrator.</p>
    </main>
  )
}
