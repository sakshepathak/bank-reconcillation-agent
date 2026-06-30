import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  RefreshCw, Upload, Sparkles, Users, ScrollText, ArrowRight,
  TrendingUp, Landmark, Wallet, CheckCircle2, Clock,
} from 'lucide-react'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import { Skeleton } from '@/components/ui/skeleton'
import { cn, formatCurrency, formatPct, formatDate } from '@/lib/utils'
import MatchaMark from '@/components/MatchaMark'
import MatchaCup from '@/components/MatchaCup'
import type { DashboardStats, RunSummary, BankAccount } from '@/types'

/** Three rising steam wisps, tinted for light or dark backgrounds. */
function Steam({ tone = 'matcha' }: { tone?: 'matcha' | 'light' }) {
  return (
    <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 flex gap-1" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className={cn('block w-[3px] h-3.5 rounded-full animate-steam', tone === 'light' ? 'bg-white/45' : 'bg-primary/30')}
          style={{ animationDelay: `${i * 0.5}s` }}
        />
      ))}
    </span>
  )
}

/* ── Greeting ─────────────────────────────────────────────────────────────── */

function greeting(): string {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

/* ── A capability tile — advertises a feature AND is the door into it ──────── */

function CapabilityTile({
  to, icon: Icon, title, description, soon = false,
}: {
  to: string
  icon: React.ElementType
  title: string
  description: string
  soon?: boolean
}) {
  const inner = (
    <>
      <MatchaMark className="pointer-events-none absolute -right-3 -bottom-3 w-16 h-16 text-primary/[0.05] group-hover:text-primary/15 transition-colors duration-200" />
      <div className="relative flex items-start justify-between">
        <div className="w-10 h-10 rounded-xl bg-primary-subtle text-primary flex items-center justify-center group-hover:animate-bob">
          <Icon className="w-5 h-5" />
        </div>
        {soon ? (
          <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground bg-muted px-2 py-1 rounded-full">
            Soon
          </span>
        ) : (
          <ArrowRight className="w-4 h-4 text-muted-foreground/50 group-hover:text-primary group-hover:translate-x-0.5 transition-all" />
        )}
      </div>
      <div className="relative mt-4">
        <p className="text-[15px] font-semibold text-foreground">{title}</p>
        <p className="text-sm text-muted-foreground mt-1 leading-snug">{description}</p>
      </div>
    </>
  )

  const base =
    'group relative overflow-hidden flex flex-col justify-between min-h-[150px] p-5 rounded-xl border bg-card shadow-sm transition-all duration-150'

  if (soon) {
    return (
      <div className={cn(base, 'opacity-75 cursor-default select-none')} aria-disabled>
        {inner}
      </div>
    )
  }

  return (
    <Link
      to={to}
      className={cn(base, 'hover:shadow-md hover:-translate-y-0.5 active:translate-y-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background')}
    >
      {inner}
    </Link>
  )
}

/* ── The hero — the primary job, front and centre ─────────────────────────── */

function ReconcileHero({
  loading, pending, accountsWithWork, unreconciled, currency, hasAccounts,
}: {
  loading: boolean
  pending: number
  accountsWithWork: number
  unreconciled: number
  currency: string
  hasAccounts: boolean
}) {
  const caughtUp = hasAccounts && pending === 0

  return (
    <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-primary to-[hsl(89_52%_22%)] text-primary-foreground shadow-lg sm:col-span-2 lg:col-span-2 lg:row-span-2 p-7 flex flex-col justify-between min-h-[316px]">
      {/* texture, a reconcile watermark up top, and Matcha steaming below-right */}
      <div className="pointer-events-none absolute inset-0 paper-grain opacity-50" />
      <RefreshCw className="pointer-events-none absolute -right-6 -top-8 w-44 h-44 text-white/[0.08]" strokeWidth={1.25} />
      <div className="pointer-events-none absolute right-6 bottom-5 hidden sm:block">
        <Steam tone="light" />
        <MatchaCup className="w-16 h-16 animate-bob drop-shadow" />
      </div>

      <div className="relative">
        <p className="text-sm font-medium text-white/70 flex items-center gap-2">
          <RefreshCw className="w-4 h-4" /> Reconciliation
        </p>

        {loading ? (
          <div className="mt-6 space-y-3">
            <Skeleton className="h-12 w-40 bg-white/20" />
            <Skeleton className="h-4 w-56 bg-white/15" />
          </div>
        ) : !hasAccounts ? (
          <div className="mt-5">
            <h2 className="font-display text-2xl font-semibold tracking-tight">Let's get your books reconciled</h2>
            <p className="text-white/75 mt-1.5 max-w-md">
              Add a bank account and import a statement — the engine will match it to your invoices and bills automatically.
            </p>
          </div>
        ) : caughtUp ? (
          <div className="mt-5">
            <h2 className="font-display text-3xl font-semibold tracking-tight flex items-center gap-2">
              <CheckCircle2 className="w-8 h-8" /> You're all caught up
            </h2>
            <p className="text-white/75 mt-1.5">Every imported transaction is reconciled. Cup's empty — nice work. 🍵</p>
          </div>
        ) : (
          <div className="mt-5">
            <div className="flex items-baseline gap-2.5">
              <span className="font-mono text-6xl font-bold leading-none tracking-tight">{pending}</span>
              <span className="text-lg text-white/80 pb-1">to reconcile</span>
            </div>
            <p className="text-white/75 mt-3">
              {formatCurrency(unreconciled, currency)} unmatched across{' '}
              {accountsWithWork} {accountsWithWork === 1 ? 'account' : 'accounts'}
            </p>
          </div>
        )}
      </div>

      <div className="relative mt-6">
        {!hasAccounts ? (
          <Link
            to="/bank-accounts"
            className="inline-flex items-center gap-2 rounded-lg bg-card text-primary font-semibold px-5 py-2.5 shadow-sm hover:bg-white active:scale-[.98] transition-all"
          >
            <Landmark className="w-4 h-4" /> Add a bank account
          </Link>
        ) : (
          <Link
            to="/reconciliation"
            className="inline-flex items-center gap-2 rounded-lg bg-card text-primary font-semibold px-5 py-2.5 shadow-sm hover:bg-white active:scale-[.98] transition-all"
          >
            {caughtUp ? 'Open reconciliation' : 'Start reconciling'}
            <ArrowRight className="w-4 h-4" />
          </Link>
        )}
      </div>
    </div>
  )
}

/* ── At-a-glance: metrics, demoted to a calm strip ───────────────────────── */

function MetricItem({
  icon: Icon, label, value,
}: {
  icon: React.ElementType
  label: string
  value: string | number
}) {
  return (
    <div className="flex items-center gap-3">
      <div className="w-9 h-9 rounded-lg bg-muted text-muted-foreground flex items-center justify-center flex-shrink-0">
        <Icon className="w-4 h-4" />
      </div>
      <div className="min-w-0">
        <p className="text-lg font-semibold text-foreground leading-tight">{value}</p>
        <p className="text-xs text-muted-foreground truncate">{label}</p>
      </div>
    </div>
  )
}

/* ── Page ─────────────────────────────────────────────────────────────────── */

export default function Dashboard() {
  const { user } = useAuth()
  const firstName = user?.name?.trim().split(/\s+/)[0]

  const { data: stats, isLoading: statsLoading } = useQuery<DashboardStats>({
    queryKey: ['dashboard', 'stats'],
    queryFn: () => api.get('/dashboard/stats').then((r) => r.data),
  })

  const { data: accounts, isLoading: acctLoading } = useQuery<BankAccount[]>({
    queryKey: ['bank-accounts'],
    queryFn: () => api.get('/bank-accounts/').then((r) => r.data),
  })

  const { data: runs, isLoading: runsLoading } = useQuery<RunSummary[]>({
    queryKey: ['runs'],
    queryFn: () => api.get('/runs/').then((r) => r.data),
  })

  const accts = accounts ?? []
  const pendingTotal = accts.reduce((s, a) => s + (a.pending_count || 0), 0)
  const accountsWithWork = accts.filter((a) => (a.pending_count || 0) > 0).length
  const unreconciled = accts.reduce((s, a) => s + Math.abs(a.balance_difference || 0), 0)
  const currency = accts[0]?.currency ?? 'GBP'

  return (
    <div className="space-y-5 animate-in fade-in-0 duration-300">
      {/* Greeting */}
      <div className="flex items-center gap-3.5">
        <div className="relative flex-shrink-0">
          <Steam />
          <div className="w-12 h-12 rounded-2xl bg-primary-subtle flex items-center justify-center animate-bob">
            <MatchaCup className="w-8 h-8" />
          </div>
        </div>
        <div>
          <h1 className="font-display text-[28px] font-semibold tracking-tight text-foreground">
            {greeting()}{firstName ? `, ${firstName}` : ''}
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Freshly whisked. Pick up where you left off, or explore what Matcha can do.
          </p>
        </div>
      </div>

      {/* Bento grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 lg:auto-rows-fr">
        <ReconcileHero
          loading={acctLoading}
          pending={pendingTotal}
          accountsWithWork={accountsWithWork}
          unreconciled={unreconciled}
          currency={currency}
          hasAccounts={accts.length > 0}
        />

        <CapabilityTile
          to="/bank-accounts"
          icon={Upload}
          title="Import statements"
          description="Drop a bank statement, invoices or bills — CSV or PDF. Matcha steeps the rest."
        />
        <CapabilityTile
          to="/reconciliation"
          icon={Sparkles}
          title="Smart matching"
          description="Matcha spots the vendor behind every messy bank line — and shows its working."
        />
        <CapabilityTile
          to="/contacts"
          icon={Users}
          title="Contacts"
          description="Customers and suppliers, balances and history in one place."
        />
        <CapabilityTile
          to="/audit"
          icon={ScrollText}
          title="Audit trail"
          description="Every decision recorded and explainable — nothing left at the bottom of the cup."
        />

        {/* At a glance — metrics, demoted */}
        <div className="sm:col-span-2 lg:col-span-2 rounded-xl border bg-card shadow-sm p-5">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            <MatchaMark className="w-3.5 h-3.5 text-primary/60" /> At a glance
          </p>
          {statsLoading ? (
            <div className="grid grid-cols-2 gap-4 mt-4">
              {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-x-6 gap-y-4 mt-4">
              <MetricItem icon={TrendingUp} label="Overall match rate" value={formatPct(stats?.overall_match_rate ?? 0)} />
              <MetricItem icon={Landmark} label={accts.length === 1 ? 'Bank account' : 'Bank accounts'} value={accts.length} />
              <MetricItem icon={Wallet} label="Transactions processed" value={stats?.total_transactions ?? 0} />
              <MetricItem icon={Users} label="Contacts" value={stats?.total_contacts ?? 0} />
            </div>
          )}
        </div>

        {/* Recent activity — replaces the opaque run-id log */}
        <div className="sm:col-span-2 lg:col-span-2 rounded-xl border bg-card shadow-sm p-5 flex flex-col">
          <div className="flex items-center justify-between">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Recent activity
            </p>
            {!!runs?.length && (
              <Link to="/audit" className="text-xs font-medium text-primary hover:underline">
                View all
              </Link>
            )}
          </div>

          {runsLoading ? (
            <div className="space-y-2 mt-4">
              {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
            </div>
          ) : !runs?.length ? (
            <div className="flex-1 flex flex-col items-center justify-center text-center py-6">
              <Clock className="w-7 h-7 text-muted-foreground/40 mb-2" />
              <p className="text-sm text-muted-foreground">
                No reconciliation runs yet.<br />Import a statement to get started.
              </p>
            </div>
          ) : (
            <div className="mt-3 divide-y divide-border/60">
              {runs.slice(0, 4).map((run) => (
                <div key={run.run_id} className="flex items-center justify-between gap-4 py-2.5">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground">
                      {run.total} transactions
                    </p>
                    <p className="text-xs text-muted-foreground" title={run.run_id}>
                      {formatDate(run.created_at)}
                      {run.pending > 0 && <span className="text-warning"> · {run.pending} pending</span>}
                    </p>
                  </div>
                  <div className="flex items-center gap-3 flex-shrink-0">
                    <span className="text-sm font-mono font-semibold text-foreground">
                      {formatPct(run.match_rate)}
                    </span>
                    <div className="w-16 h-1.5 bg-muted rounded-full overflow-hidden">
                      <div className="h-full bg-primary rounded-full" style={{ width: `${run.match_rate}%` }} />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* a little sign-off with personality */}
      <p className="text-center text-xs text-muted-foreground/70 pt-1 flex items-center justify-center gap-1.5">
        <MatchaMark className="w-3.5 h-3.5 text-primary/50" />
        Reconciliation, one sip at a time.
      </p>
    </div>
  )
}
