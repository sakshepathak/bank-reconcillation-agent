/**
 * Auth context — single source of truth for "who am I?" on the frontend.
 *
 * Mounted ABOVE the router so every page has access to the current user.
 * Uses TanStack Query to cache /auth/me. All mutations that change which
 * org the session is acting on (login/logout/switch/createOrg) carefully
 * tear down cached org-scoped data so the next render starts from a clean
 * slate — this is what guarantees no data from org A bleeds into org B.
 */
import { createContext, useContext, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { api, ApiError } from './api'

// ── Types (shape mirrors backend AuthMeResponse) ─────────────────────────────

export interface OrgSummary {
  id: number
  name: string
  role: string
}

export interface AuthMe {
  user_id: number
  email: string
  name: string
  current_org_id: number | null
  orgs: OrgSummary[]
}

export interface LoginBody {
  email: string
  password: string
}

export interface RegisterBody {
  email: string
  password: string
  name: string
  org_name: string
}

export interface CreateOrgBody {
  name: string
  country?: string
  currency?: string
  industry?: string | null
  vat_registered?: boolean
  vat_number?: string | null
  tax_treatment?: string
  financial_year_end_day?: number
  financial_year_end_month?: number
}

// Returned by POST /orgs and GET /orgs/current.
export interface OrgFull {
  id: number
  name: string
  country: string | null
  currency: string
  industry: string | null
  vat_registered: boolean
  vat_number: string | null
  tax_treatment: string
  financial_year_end_day: number
  financial_year_end_month: number
  created_at: string
  updated_at: string
  role: string | null
}

interface AuthContextValue {
  user: AuthMe | null
  isLoading: boolean
  login: (body: LoginBody) => Promise<AuthMe>
  register: (body: RegisterBody) => Promise<AuthMe>
  logout: () => Promise<void>
  switchOrg: (orgId: number) => Promise<AuthMe>
  createOrg: (body: CreateOrgBody) => Promise<OrgFull>
  deleteOrg: (orgId: number) => Promise<void>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

// ── Cache helpers ────────────────────────────────────────────────────────────

/**
 * Drop every cached query that isn't the auth-me query. Used on every
 * org-context-change transition (login, logout, switchOrg, createOrg) so
 * the next page render starts with no stale data from the previous org.
 *
 * Why `removeQueries` rather than `invalidateQueries`:
 *   • invalidate marks queries stale and triggers a refetch on observers.
 *     Until that refetch resolves, components still see the OLD cached
 *     data (just with isFetching=true). That's a real "leak" window.
 *   • remove DROPS the cache entry entirely. Observers re-mount into a
 *     loading state and fetch fresh. No window where org A's bills are
 *     visible to org B's user.
 */
function resetOrgScopedCache(qc: QueryClient) {
  qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'auth-me' })
}

// ── Network functions ────────────────────────────────────────────────────────

async function fetchMe(): Promise<AuthMe | null> {
  try {
    const { data } = await api.get<AuthMe>('/auth/me')
    return data
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return null
    throw err
  }
}

// ── Provider ─────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()

  const { data: user, isLoading } = useQuery<AuthMe | null>({
    queryKey: ['auth-me'],
    queryFn: fetchMe,
    retry: false,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: true,
  })

  const loginMutation = useMutation({
    mutationFn: async (body: LoginBody) => {
      const { data } = await api.post<AuthMe>('/auth/login', body)
      return data
    },
    onSuccess: (data) => {
      // Drop any cache from a previous session (e.g. previous user on this device).
      resetOrgScopedCache(qc)
      qc.setQueryData(['auth-me'], data)
    },
  })

  const registerMutation = useMutation({
    mutationFn: async (body: RegisterBody) => {
      const { data } = await api.post<AuthMe>('/auth/register', body)
      return data
    },
    onSuccess: (data) => {
      resetOrgScopedCache(qc)
      qc.setQueryData(['auth-me'], data)
    },
  })

  const logoutMutation = useMutation({
    mutationFn: async () => {
      await api.post('/auth/logout')
    },
    onSuccess: () => {
      qc.setQueryData(['auth-me'], null)
      resetOrgScopedCache(qc)
    },
  })

  const switchOrgMutation = useMutation({
    mutationFn: async (orgId: number) => {
      const { data } = await api.put<AuthMe>('/auth/current-org', { org_id: orgId })
      return data
    },
    onSuccess: (data) => {
      // Order matters: drop the OLD org's cache BEFORE the new auth-me lands,
      // so observers don't briefly see stale data on the new org's page.
      resetOrgScopedCache(qc)
      qc.setQueryData(['auth-me'], data)
    },
  })

  const createOrgMutation = useMutation({
    mutationFn: async (body: CreateOrgBody) => {
      const { data } = await api.post<OrgFull>('/orgs/', body)
      return data
    },
    onSuccess: async () => {
      // Backend auto-switches the session to the new org. We have to:
      //   1. Drop cached data from the org we WERE on (it doesn't belong to
      //      the new org's view).
      //   2. Refetch /auth/me so the OrgSwitcher + RequireOrg see the new
      //      current_org_id immediately.
      // We await the refetch so callers that navigate('/dashboard') right
      // after createOrg don't render against the stale auth-me cache.
      resetOrgScopedCache(qc)
      await qc.invalidateQueries({ queryKey: ['auth-me'] })
    },
  })

  const deleteOrgMutation = useMutation({
    mutationFn: async (orgId: number) => {
      await api.delete(`/orgs/${orgId}`)
    },
    onSuccess: async () => {
      // The backend wiped the org and reset the session's current_org_id to
      // null. Drop all org-scoped cache and refetch /auth/me so the org is gone
      // from the switcher and RequireOrg drops the user to the picker — a true
      // clean slate, no stale data from the deleted org lingering anywhere.
      resetOrgScopedCache(qc)
      await qc.invalidateQueries({ queryKey: ['auth-me'] })
    },
  })

  const value: AuthContextValue = {
    user: user ?? null,
    isLoading,
    login: loginMutation.mutateAsync,
    register: registerMutation.mutateAsync,
    logout: async () => {
      await logoutMutation.mutateAsync()
    },
    switchOrg: switchOrgMutation.mutateAsync,
    createOrg: createOrgMutation.mutateAsync,
    deleteOrg: async (orgId: number) => {
      await deleteOrgMutation.mutateAsync(orgId)
    },
    refresh: async () => {
      await qc.invalidateQueries({ queryKey: ['auth-me'] })
    },
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth() must be used inside <AuthProvider>')
  return ctx
}

// ── Probe for whether registration is open ───────────────────────────────────
// Used by /register page to decide whether to render the form or bounce
// the user to /login.

export async function fetchRegisterEnabled(): Promise<boolean> {
  const { data } = await api.get<{ enabled: boolean }>('/auth/register-enabled')
  return data.enabled
}
