/**
 * Route guard — wrap protected routes. Behavior:
 *   - while loading auth state: render nothing (briefly, ~ms)
 *   - if logged out: redirect to /login, preserving the original path
 *   - if logged in: render children
 */
import { Navigate, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from '@/lib/auth-context'

export default function RequireAuth({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    // Avoid a flash of /login while the initial /auth/me request is in flight.
    return null
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return <>{children}</>
}
