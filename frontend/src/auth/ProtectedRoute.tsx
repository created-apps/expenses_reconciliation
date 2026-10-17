import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from '@/auth/context'

/** Renders the nested routes only for a signed-in, allowed user. Everyone else goes to /login. */
export default function ProtectedRoute() {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return <main className="p-8 text-sm text-muted-foreground">Loading…</main>
  }
  if (status === 'signed-out') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return <Outlet />
}
