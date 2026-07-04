import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  RefreshCw, Upload, Sparkles, Users, ScrollText, ArrowRight,
  Landmark, Wallet, CheckCircle2, Clock,
} from 'lucide-react'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import { Skeleton } from '@/components/ui/skeleton'
import { cn, formatCurrency, formatPct, formatDate } from '@/lib/utils'
import MatchaMark from '@/components/MatchaMark'
import MatchaCup from '@/components/MatchaCup'
import MatchaCupGauge from '@/components/MatchaCupGauge'
import MatchingInstrument from '@/components/MatchingInstrument'
import { Leaf, Whisk, Sparkle, Coin, Bean, ScatterDoodles } from '@/components/Doodles'
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

/* ── Greeting + Matcha's intelligent read on the day ──────────────────────── */

function greeting(): string {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

type Insight = { text: string; cta?: { to: string; label: string } }

/** Matcha's line is derived straight from the numbers — no LLM needed when the
 *  data already says what matters. */
function computeInsight(a: {
  hasAccounts: boolean; caughtUp: boolean; pending: number
  unreconciled: number; currency: string; matchRate: number
}): Insight {
  if (!a.hasAccounts) {
    return {
      text: "Let's brew your first cup — add a bank account and drop in a statement. I'll match it to your invoices and bills automatically.",
      cta: { to: '/bank-accounts', label: 'Add a bank account' },
    }
  }
  if (a.caughtUp) {
    return {
      text: `Spotless — every line's reconciled and the cup's empty${a.matchRate ? `, ${formatPct(a.matchRate)} matched` : ''}. Go take a proper break. 🍵`,
    }
  }
  return {
    text: `You've got ${a.pending} line${a.pending === 1 ? '' : 's'} waiting (${formatCurrency(a.unreconciled, a.currency)}). I can auto-match most of them in one whisk — shall we?`,
    cta: { to: '/reconciliation', label: 'Start reconciling' },
  }
}

function MatchaSays({
  firstName, loading, insight,
}: {
  firstName?: string
  loading: boolean
  insight: Insight
}) {
  return (
    <div className="relative overflow-hidden rounded-2xl border bg-card shadow-sm p-5 sm:p-6">
      {/* doodles peeking in */}
      <Leaf className="absolute right-6 top-4 w-8 h-8 text-primary/[0.12] -rotate-12 animate-sway" />
      <Sparkle className="absolute right-[30%] bottom-4 w-6 h-6 text-primary/[0.12]" />
      <Whisk className="absolute right-[16%] -bottom-3 w-12 h-12 text-primary/[0.06] rotate-6" />
      <Coin className="absolute right-3 bottom-6 w-6 h-6 text-primary/[0.10]" />

      <div className="relative flex items-center gap-4 sm:gap-5">
        {/* the mascot */}
        <div className="relative flex-shrink-0">
          <Steam />
          <div className="w-16 h-16 sm:w-[72px] sm:h-[72px] rounded-2xl bg-primary-subtle grid place-items-center animate-bob shadow-sm">
            <MatchaCup className="w-11 h-11 sm:w-12 sm:h-12" />
          </div>
        </div>

        {/* what Matcha has to say */}
        <div className="relative min-w-0 flex-1">
          <h1 className="font-display text-[26px] sm:text-[30px] font-semibold tracking-tight text-foreground leading-none">
            {greeting()}{firstName ? `, ${firstName}` : ''}
          </h1>
          <p className="text-sm sm:text-[15px] text-muted-foreground mt-2 max-w-2xl leading-snug">
            {loading ? 'Warming the whisk…' : insight.text}
          </p>
        </div>

        {/* the smart next step */}
        {!loading && insight.cta && (
          <Link
            to={insight.cta.to}
            className="hidden md:inline-flex items-center gap-2 rounded-xl bg-primary text-primary-foreground font-semibold px-4 py-2.5 shadow-sm hover:bg-primary-hover active:scale-[.98] transition-all flex-shrink-0"
          >
            {insight.cta.label} <ArrowRight className="w-4 h-4" />
          </Link>
        )}
      </div>
    </div>
  )
}

/* ── A capability tile — advertises a feature AND is the door into it ──────── */

function CapabilityTile({
  to, icon: Icon, doodle: Doodle, title, description,
}: {
  to: string
  icon: React.ElementType
  doodle: React.ElementType
  title: string
  description: string
}) {
  return (
    <Link
      to={to}
      className="group relative overflow-hidden flex flex-col justify-between min-h-[152px] p-5 rounded-2xl border bg-card shadow-sm transition-all duration-150 hover:shadow-md hover:-translate-y-0.5 active:translate-y-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
    >
      <Doodle className="pointer-events-none absolute -right-3 -bottom-3 w-16 h-16 text-primary/[0.07] group-hover:text-primary/20 transition-colors duration-200 -rotate-12" />
      <Sparkle className="pointer-events-none absolute right-3 top-3 w-4 h-4 text-transparent group-hover:text-primary/40 transition-colors duration-200" />

      <div className="relative flex items-start justify-between">
        <div className="w-11 h-11 rounded-2xl bg-primary-subtle text-primary flex items-center justify-center group-hover-wiggle">
          <Icon className="w-5 h-5" />
        </div>
        <ArrowRight className="w-4 h-4 text-muted-foreground/50 group-hover:text-primary group-hover:translate-x-0.5 transition-all" />
      </div>
      <div className="relative mt-4">
        <p className="text-[15px] font-semibold text-foreground">{title}</p>
        <p className="text-sm text-muted-foreground mt-1 leading-snug">{description}</p>
      </div>
    </Link>
  )
}

/* ── The reconcile hero — the primary job, front and centre ────────────────── */

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
    <div className="relative overflow-hidden h-full rounded-2xl bg-gradient-to-br from-[hsl(89_46%_32%)] to-[hsl(89_52%_22%)] text-white shadow-lg p-7 flex flex-col justify-between min-h-[316px]">
      <div className="pointer-events-none absolute inset-0 paper-grain opacity-50" />
      <RefreshCw className="pointer-events-none absolute -right-6 -top-8 w-44 h-44 text-white/[0.08]" strokeWidth={1.25} />
      <Sparkle className="pointer-events-none absolute left-7 bottom-8 w-6 h-6 text-white/15" />
      <Leaf className="pointer-events-none absolute left-[38%] top-6 w-7 h-7 text-white/10 rotate-12 animate-sway" />
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
        <Link
          to={hasAccounts ? '/reconciliation' : '/bank-accounts'}
          className="inline-flex items-center gap-2 rounded-lg bg-card text-primary font-semibold px-5 py-2.5 shadow-sm hover:bg-white dark:hover:bg-muted active:scale-[.98] transition-all"
        >
          {!hasAccounts ? (
            <><Landmark className="w-4 h-4" /> Add a bank account</>
          ) : (
            <>{caughtUp ? 'Open reconciliation' : 'Start reconciling'} <ArrowRight className="w-4 h-4" /></>
          )}
        </Link>
      </div>
    </div>
  )
}

/* ── Playful stat widgets ─────────────────────────────────────────────────── */

function StatWidget({
  icon: Icon, doodle: Doodle, value, label,
}: {
  icon: React.ElementType
  doodle: React.ElementType
  value: string | number
  label: string
}) {
  return (
    <div className="group relative overflow-hidden rounded-2xl border bg-card shadow-sm p-4">
      <Doodle className="pointer-events-none absolute -right-2 -bottom-2 w-16 h-16 text-primary/[0.07] group-hover:text-primary/15 transition-colors -rotate-12" />
      <div className="relative w-9 h-9 rounded-xl bg-primary-subtle text-primary grid place-items-center mb-3 group-hover-wiggle">
        <Icon className="w-[18px] h-[18px]" />
      </div>
      <p className="relative font-display text-[26px] font-semibold text-foreground tabular-nums leading-none">{value}</p>
      <p className="relative text-xs text-muted-foreground mt-1.5">{label}</p>
    </div>
  )
}

function MatchRateWidget({ value, loading }: { value: number; loading: boolean }) {
  return (
    <div className="relative overflow-hidden rounded-2xl border bg-card shadow-sm p-4 flex items-center gap-3">
      <Sparkle className="pointer-events-none absolute right-2 top-2 w-5 h-5 text-primary/20" />
      {loading ? (
        <Skeleton className="w-14 h-14 rounded-2xl flex-shrink-0" />
      ) : (
        <MatchaCupGauge value={value} className="w-14 h-14 flex-shrink-0" />
      )}
      <div className="relative min-w-0">
        <p className="font-display text-[26px] font-semibold text-foreground tabular-nums leading-none">
          {loading ? '—' : formatPct(value)}
        </p>
        <p className="text-xs text-muted-foreground mt-1.5">Match rate</p>
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
  const matchRate = stats?.overall_match_rate ?? 0
  const hasAccounts = accts.length > 0
  const caughtUp = hasAccounts && pendingTotal === 0

  const insight = computeInsight({ hasAccounts, caughtUp, pending: pendingTotal, unreconciled, currency, matchRate })

  return (
    <div className="relative space-y-5 animate-in fade-in-0 duration-300">
      {/* a faint field of doodles floating behind the whole page */}
      <ScatterDoodles />

      {/* Matcha greets you with an intelligent read on the day */}
      <MatchaSays firstName={firstName} loading={acctLoading} insight={insight} />

      {/* Hero row — the matching instrument beside the reconcile call to action */}
      <div className="relative grid grid-cols-1 lg:grid-cols-2 gap-4 items-stretch">
        <MatchingInstrument />
        <ReconcileHero
          loading={acctLoading}
          pending={pendingTotal}
          accountsWithWork={accountsWithWork}
          unreconciled={unreconciled}
          currency={currency}
          hasAccounts={hasAccounts}
        />
      </div>

      {/* Playful stat widgets */}
      <div className="relative grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MatchRateWidget value={matchRate} loading={statsLoading} />
        <StatWidget icon={Landmark} doodle={Coin} value={accts.length} label={accts.length === 1 ? 'Bank account' : 'Bank accounts'} />
        <StatWidget icon={Wallet} doodle={Bean} value={stats?.total_transactions ?? 0} label="Lines processed" />
        <StatWidget icon={Users} doodle={Leaf} value={stats?.total_contacts ?? 0} label="Contacts" />
      </div>

      {/* Capabilities */}
      <div className="relative grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <CapabilityTile
          to="/bank-accounts"
          icon={Upload}
          doodle={Coin}
          title="Import statements"
          description="Drop a bank statement, invoices or bills — CSV or PDF. Matcha does the rest."
        />
        <CapabilityTile
          to="/reconciliation"
          icon={Sparkles}
          doodle={Whisk}
          title="Smart matching"
          description="Matcha spots the vendor behind every messy bank line — and shows its working."
        />
        <CapabilityTile
          to="/contacts"
          icon={Users}
          doodle={Leaf}
          title="Contacts"
          description="Customers and suppliers, balances and history in one place."
        />
        <CapabilityTile
          to="/audit"
          icon={ScrollText}
          doodle={Bean}
          title="Audit trail"
          description="Every decision recorded and explainable — end to end."
        />
      </div>

      {/* Recent activity */}
      <div className="relative rounded-2xl border bg-card shadow-sm p-5">
        <div className="flex items-center justify-between">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            <MatchaMark className="w-3.5 h-3.5 text-primary/60" /> Recent activity
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
          <div className="flex flex-col items-center justify-center text-center py-8">
            <div className="relative mb-2">
              <Steam />
              <Clock className="w-7 h-7 text-muted-foreground/40" />
            </div>
            <p className="text-sm text-muted-foreground">
              No reconciliation runs yet.<br />Import a statement and I'll get whisking.
            </p>
          </div>
        ) : (
          <div className="mt-3 divide-y divide-border/60">
            {runs.slice(0, 5).map((run) => (
              <div key={run.run_id} className="flex items-center justify-between gap-4 py-2.5">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground">{run.total} transactions</p>
                  <p className="text-xs text-muted-foreground" title={run.run_id}>
                    {formatDate(run.created_at)}
                    {run.pending > 0 && <span className="text-warning"> · {run.pending} pending</span>}
                  </p>
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  <span className="text-sm font-mono font-semibold text-foreground">{formatPct(run.match_rate)}</span>
                  <div className="w-16 h-1.5 bg-muted rounded-full overflow-hidden">
                    <div className="h-full bg-primary rounded-full" style={{ width: `${run.match_rate}%` }} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* a little sign-off with personality */}
      <p className="relative text-center text-xs text-muted-foreground/70 pt-1 flex items-center justify-center gap-1.5">
        <MatchaMark className="w-3.5 h-3.5 text-primary/50" />
        Reconciliation, one sip at a time.
      </p>
    </div>
  )
}
