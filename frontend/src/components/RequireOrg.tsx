/**
 * Org guard — wrap pages that require the user to have at least one org.
 *
 * Assumes RequireAuth has already run, so `user` is non-null here. If the
 * user has zero orgs (e.g. first sign-in after a migration that didn't
 * auto-create one, or a user whose only org was deleted) we bounce to the
 * "Add your business" page. The user CANNOT use the app without picking
 * which set of books they're acting on — that's the whole point of the
 * multi-tenant refactor.
 */
import { Navigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from '@/lib/auth-context'

export default function RequireOrg({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth()

  if (isLoading) return null

  // Defensive: RequireAuth should have caught this, but if for some reason
  // the chain ran out of order, bounce to login rather than crash on `user.orgs`.
  if (!user) return <Navigate to="/login" replace />

  // No memberships at all, OR session has no current_org → force onboarding.
  if (user.orgs.length === 0 || user.current_org_id === null) {
    return <Navigate to="/onboarding" replace />
  }

  return <>{children}</>
}
