import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useIsFetching, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as Dialog from '@radix-ui/react-dialog'
import { useConfirm } from '@/components/ConfirmProvider'
import { useToast } from '@/components/ToastProvider'
import {
  Check, ArrowRightLeft, MessageSquare, Plus, Sparkles,
  Landmark, Loader2, ChevronDown, ChevronUp, ArrowDownUp, Rows3, LayoutList,
  Scale, Clock, ArrowRight,
} from 'lucide-react'
import { api, ApiError } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { PageHeader } from '@/components/ui/page-header'
import { StatStrip } from '@/components/ui/stat-strip'
import { cn, formatCurrency, formatDate } from '@/lib/utils'
import { viewFor, THRESHOLDS } from '@/lib/match'
import { RotateCcw, CheckCircle2, AlertTriangle } from 'lucide-react'
import type { BankAccount, StatementLine, ReconciledLine, UnreconcileResult, Bill, Invoice } from '@/types'

interface Suggestion {
  type: 'invoice' | 'bill'
  id: number
  label: string
  contact_name: string
  date: string
  amount: number
  currency: string
  score: number
  reason: string
  method: string                // alias-exact | canonical-exact | fuzzy | fuzzy+embed | no-name
}

interface BulkOpenDoc {
  id: number
  label: string
  amount: number
  date: string
  contact_name: string
}

interface BulkMatchData {
  vendor: string | null
  vendor_score: number
  doc_type: 'invoice' | 'bill'
  open_docs: BulkOpenDoc[]
  suggested_groups: number[][]  // [[id1,id2,id3], ...]
}

type SubTab = 'match' | 'create' | 'transfer' | 'discuss'

// Thresholds come from the central match module so UI + future logic stay in sync.
const { MID_LOW } = THRESHOLDS

// ─────────────────────────────────────────────────────────────────────────────
// Top-level page
// ─────────────────────────────────────────────────────────────────────────────

export default function Reconciliation() {
  const [searchParams, setSearchParams] = useSearchParams()
  const accountIdParam = searchParams.get('account')
  const accountId = accountIdParam ? parseInt(accountIdParam) : null

  const { data: accounts, isLoading: accountsLoading } = useQuery<BankAccount[]>({
    queryKey: ['bank-accounts'],
    queryFn: () => api.get('/bank-accounts/').then((r) => r.data),
  })

  const { data: lines, isLoading: linesLoading } = useQuery<StatementLine[]>({
    queryKey: ['statement-lines', accountId, 'pending'],
    queryFn: () =>
      api
        .get('/statement-lines/', { params: { bank_account_id: accountId, status: 'pending' } })
        .then((r) => r.data),
    enabled: accountId !== null,
  })

  const account = accounts?.find((a) => a.id === accountId) ?? null

  if (!accountId) {
    return (
      <ReconcileOverview
        accounts={accounts ?? []}
        loading={accountsLoading}
        onPick={(id) => setSearchParams({ account: String(id) })}
      />
    )
  }

  return (
    <ReconcileForAccount
      accountId={accountId}
      account={account}
      lines={lines ?? []}
      linesLoading={linesLoading}
      accounts={accounts ?? []}
    />
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Reconcile overview — the landing screen when no account is selected yet.
// Summary band + rich, full-width account rows.
// ─────────────────────────────────────────────────────────────────────────────

function ReconcileOverview({
  accounts, loading, onPick,
}: {
  accounts: BankAccount[]
  loading: boolean
  onPick: (id: number) => void
}) {
  const totalPending = accounts.reduce((s, a) => s + (a.pending_count || 0), 0)
  const outOfBalance = accounts.reduce((s, a) => s + Math.abs(a.balance_difference || 0), 0)
  const reconciledCount = accounts.filter((a) => Math.abs(a.balance_difference || 0) < 0.01).length
  const lastImport = accounts.reduce<string | null>(
    (latest, a) => (a.last_imported_at && (!latest || a.last_imported_at > latest) ? a.last_imported_at : latest),
    null,
  )
  const currency = accounts[0]?.currency ?? 'GBP'

  return (
    <div className="space-y-5 animate-in fade-in-0 duration-300">
      <PageHeader
        title="Reconcile"
        subtitle="Pick an account to start matching its bank lines against your invoices and bills."
      />

      <StatStrip
        stats={[
          { label: 'Lines to reconcile', value: totalPending, icon: AlertTriangle, accent: totalPending > 0 },
          { label: 'Out of balance', value: formatCurrency(outOfBalance, currency), icon: Scale },
          { label: 'Bank accounts', value: accounts.length, icon: Landmark,
            sub: accounts.length ? `${reconciledCount} reconciled` : undefined },
          { label: 'Last import', value: lastImport ? formatDate(lastImport) : '—', icon: Clock },
        ]}
      />

      <div className="space-y-2.5">
        <h2 className="px-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Your accounts</h2>
        {loading ? (
          <div className="space-y-2.5">
            {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-20 w-full" />)}
          </div>
        ) : accounts.length === 0 ? (
          <Card>
            <CardContent className="py-12 text-center">
              <Landmark className="w-8 h-8 text-muted-foreground mx-auto mb-3 opacity-40" />
              <p className="text-sm text-muted-foreground">No bank accounts yet. Add one to start reconciling.</p>
            </CardContent>
          </Card>
        ) : (
          accounts.map((a) => <AccountRow key={a.id} a={a} onPick={onPick} />)
        )}
      </div>
    </div>
  )
}

function AccountRow({ a, onPick }: { a: BankAccount; onPick: (id: number) => void }) {
  const reconciled = Math.abs(a.balance_difference) < 0.01
  return (
    <Card className="hover:border-primary/60 transition-colors">
      <CardContent className="p-4">
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-3 min-w-0 flex-1">
            <div className="w-10 h-10 rounded-lg bg-primary-subtle text-primary flex items-center justify-center flex-shrink-0">
              <Landmark className="w-5 h-5" />
            </div>
            <div className="min-w-0">
              <p className="font-semibold text-sm truncate">{a.name}</p>
              <p className="text-[11px] text-muted-foreground font-mono truncate">
                {a.bank_name ? `${a.bank_name} · ` : ''}{a.account_number ?? 'No number'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-6 flex-shrink-0">
            <Mini label="Statement" value={formatCurrency(a.statement_balance, a.currency)} />
            <Mini label="OOO Balance" value={formatCurrency(a.ooo_balance, a.currency)} />
            <div className="text-right">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Difference</p>
              <p className={cn('text-sm font-bold font-mono', reconciled ? 'text-emerald-600' : 'text-foreground')}>
                {formatCurrency(a.balance_difference, a.currency)}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3 flex-shrink-0">
            {a.pending_count > 0 ? (
              <Badge variant="warning">{a.pending_count} pending</Badge>
            ) : (
              <Badge variant="success"><Check className="w-3 h-3 mr-1" />Reconciled</Badge>
            )}
            <Button size="sm" onClick={() => onPick(a.id)}>
              Reconcile <ArrowRight className="w-3.5 h-3.5 ml-1" />
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-right">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="text-sm font-semibold font-mono text-foreground">{value}</p>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────

function ReconcileForAccount({
  accountId, account, lines, linesLoading, accounts,
}: {
  accountId: number
  account: BankAccount | null
  lines: StatementLine[]
  linesLoading: boolean
  accounts: BankAccount[]
}) {
  const navigate = useNavigate()
  const reconciled = account ? Math.abs(account.balance_difference) < 0.01 : false

  // How many statement lines are still being analysed for matches right now.
  // Each ReconcileRow runs its own ['suggestions', line.id] query; useIsFetching
  // counts the in-flight ones across the whole page without us threading state
  // through every row. The first request also warms up the embedding model
  // server-side (~5–10s), which is exactly when the page looked frozen before.
  const analysing = useIsFetching({ queryKey: ['suggestions'] })
  const total = lines.length
  const done = Math.max(0, total - analysing)
  const pct = total > 0 ? Math.round((done / total) * 100) : 0

  const [tab, setTab] = useState<'todo' | 'reconciled'>('todo')

  // Presentational date sort for the lines list (toggle: oldest ↔ newest). Sorts a
  // copy so we never mutate the query cache; the backend default is newest-first.
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const sortedLines = useMemo(
    () => [...lines].sort((a, b) => (sortDir === 'asc' ? 1 : -1) * a.date.localeCompare(b.date)),
    [lines, sortDir],
  )

  // Compact (dense, Xero-style) vs expanded card view. Default to compact so the
  // most lines fit on screen; the choice is remembered across sessions.
  const [compact, setCompact] = useState<boolean>(() => {
    try { return localStorage.getItem('reconcile-compact') !== 'false' } catch { return true }
  })
  const toggleCompact = () =>
    setCompact((c) => {
      const next = !c
      try { localStorage.setItem('reconcile-compact', String(next)) } catch { /* ignore */ }
      return next
    })

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <NativeSelect
              value={accountId}
              onChange={(e) => navigate(`/reconciliation?account=${e.target.value}`)}
              className="w-fit text-base font-bold"
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </NativeSelect>
            {account?.pending_count !== undefined && account.pending_count > 0 && (
              <Badge variant="warning">{account.pending_count} pending</Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            {account?.bank_name && `${account.bank_name} · `}
            {account?.account_number ?? ''}
          </p>
        </div>
      </div>

      {/* Balance bar — compact */}
      {account && (
        <Card>
          <CardContent className="py-3 px-4">
            <div className="grid grid-cols-3 gap-6">
              <BalanceCell label="Statement" value={account.statement_balance} currency={account.currency} />
              <BalanceCell label="OOO Balance" value={account.ooo_balance} currency={account.currency} />
              <div>
                <p className="text-[10px] text-muted-foreground uppercase tracking-wide">Difference</p>
                <p className={cn(
                  'text-base font-bold font-mono',
                  reconciled ? 'text-emerald-600' : 'text-amber-600',
                )}>
                  {reconciled && <Check className="w-3.5 h-3.5 inline mr-1" />}
                  {formatCurrency(account.balance_difference, account.currency)}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Tabs: switch between unreconciled lines and reconciled (undoable) ones */}
      <div className="flex items-center gap-1 border-b border-border">
        <TabBtn active={tab === 'todo'} onClick={() => setTab('todo')}>
          To reconcile
          {(account?.pending_count ?? 0) > 0 && (
            <span className="ml-1.5 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">
              {account!.pending_count}
            </span>
          )}
        </TabBtn>
        <TabBtn active={tab === 'reconciled'} onClick={() => setTab('reconciled')}>
          Reconciled
        </TabBtn>
      </div>

      {tab === 'reconciled' ? (
        <ReconciledList accountId={accountId} currency={account?.currency ?? 'GBP'} />
      ) : (
        <>

      {/* Analysis progress — a circular ring (not a bar) so the page never looks
          frozen during the matcher's cold-start work, and the user can always see
          how far along it is. Once results are cached it won't reappear on return. */}
      {!linesLoading && total > 0 && analysing > 0 && (
        <div className="flex items-center gap-3.5 rounded-xl border border-matcha-200 bg-matcha-50/70 px-4 py-3">
          <ProgressRing done={done} total={total} pct={pct} />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-matcha-900">
              Finding matches for your transactions…
            </p>
            <p className="text-[11px] text-matcha-600 mt-0.5">
              Matching each line against open invoices and bills. The first run warms up the
              matcher, so it can take a few seconds — results stay ready after that.
            </p>
          </div>
          <Loader2 className="w-4 h-4 animate-spin text-matcha-400 flex-shrink-0" />
        </div>
      )}

      {/* Lines */}
      {linesLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : !lines.length ? (
        <Card>
          <CardContent className="py-12 text-center">
            <Sparkles className="w-8 h-8 text-emerald-500 mx-auto mb-3 opacity-70" />
            <p className="text-sm font-medium">All caught up!</p>
            <p className="text-xs text-muted-foreground mt-1">
              No pending statement lines on this account.{' '}
              <button onClick={() => navigate('/bank-accounts')} className="text-primary hover:underline">
                Import another statement
              </button>{' '}
              to keep going.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2 px-1">
            <p className="text-xs font-medium text-muted-foreground">
              {lines.length} pending line{lines.length === 1 ? '' : 's'}
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={toggleCompact}
                title="Switch between compact (dense) and expanded card view"
              >
                {compact
                  ? <LayoutList className="w-3.5 h-3.5 mr-1.5" />
                  : <Rows3 className="w-3.5 h-3.5 mr-1.5" />}
                {compact ? 'Expand' : 'Compact'}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))}
                title="Sort the lines by statement date"
              >
                <ArrowDownUp className="w-3.5 h-3.5 mr-1.5" />
                {sortDir === 'asc' ? 'Oldest first' : 'Newest first'}
              </Button>
            </div>
          </div>
          <div className={compact ? 'space-y-1.5' : 'space-y-2'}>
            {sortedLines.map((line) => (
              <ReconcileRow
                key={line.id}
                line={line}
                accountId={accountId}
                currency={account?.currency ?? 'GBP'}
                otherAccounts={accounts.filter((a) => a.id !== accountId)}
                compact={compact}
              />
            ))}
          </div>
        </div>
      )}
        </>
      )}
    </div>
  )
}

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        '-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors',
        active
          ? 'border-primary text-foreground'
          : 'border-transparent text-muted-foreground hover:text-foreground',
      )}
    >
      {children}
    </button>
  )
}

function BalanceCell({ label, value, currency }: { label: string; value: number; currency: string }) {
  return (
    <div>
      <p className="text-[10px] text-muted-foreground uppercase tracking-wide">{label}</p>
      <p className="text-base font-bold font-mono">{formatCurrency(value, currency)}</p>
    </div>
  )
}

// A determinate circular progress ring (done/total in the centre) — the polished
// stand-in for the old progress bar while the matcher analyses the statement.
function ProgressRing({ done, total, pct }: { done: number; total: number; pct: number }) {
  const size = 42
  const stroke = 3.5
  const r = (size - stroke) / 2
  const circumference = 2 * Math.PI * r
  const offset = circumference * (1 - Math.max(0, Math.min(1, pct / 100)))
  return (
    <div className="relative flex-shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} className="stroke-matcha-100" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className="stroke-matcha-500 transition-[stroke-dashoffset] duration-500 ease-out"
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-[10px] font-semibold tabular-nums text-matcha-700">
        {done}/{total}
      </span>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// ReconcileRow — the compact split-pane card
// ─────────────────────────────────────────────────────────────────────────────

function ReconcileRow({
  line, accountId, currency, otherAccounts, compact,
}: {
  line: StatementLine
  accountId: number
  currency: string
  otherAccounts: BankAccount[]
  compact: boolean
}) {
  const queryClient = useQueryClient()
  const isInflow = line.received > 0
  const amount = isInflow ? line.received : line.spent

  // Fetch suggestions ONCE per row, share across tabs + tab-default logic.
  // Cache for the whole session: matching is expensive (cold-start embeddings),
  // so leaving Reconcile and coming back should be instant, never a recompute.
  // Mutations (match / unreconcile / duplicate-delete) explicitly invalidate
  // ['suggestions', ...] whenever the underlying data actually changes.
  const { data: suggestions, isLoading: suggestionsLoading } = useQuery<Suggestion[]>({
    queryKey: ['suggestions', line.id],
    queryFn: () => api.get(`/statement-lines/${line.id}/suggestions`).then((r) => r.data),
    staleTime: Infinity,
    gcTime: Infinity,
  })

  // Peek at bulk suggestions at the row level so the Match tab can show a small
  // "possible split" dot. Same query key as MatchTab → shared cache, no extra
  // network request.
  const { data: bulkData } = useQuery<BulkMatchData>({
    queryKey: ['bulk-suggestions', line.id],
    queryFn: () => api.get(`/statement-lines/${line.id}/bulk-suggestions`).then((r) => r.data),
    staleTime: Infinity,
    gcTime: Infinity,
  })
  const hasSplit = (bulkData?.suggested_groups.length ?? 0) > 0

  // Smart default tab — picked when suggestions arrive, then locked.
  // Only switch to Match when the top suggestion is confident enough; below that
  // default to Create. A possible split is surfaced as a dot on the Match tab
  // (not an auto-switch / auto-expand), so the view stays clean.
  const [tab, setTab] = useState<SubTab | null>(null)
  useEffect(() => {
    if (tab !== null || suggestions === undefined) return
    const top = suggestions[0]
    if (top && top.score >= MID_LOW) setTab('match')
    else setTab('create')
  }, [suggestions, tab])

  const activeTab: SubTab = tab ?? 'match'

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['statement-lines', accountId, 'pending'] })
    queryClient.invalidateQueries({ queryKey: ['bank-accounts'] })
    queryClient.invalidateQueries({ queryKey: ['suggestions', line.id] })
    queryClient.invalidateQueries({ queryKey: ['bulk-suggestions', line.id] })
    // Refresh invoices and bills so outstanding amounts update immediately
    queryClient.invalidateQueries({ queryKey: ['invoices'] })
    queryClient.invalidateQueries({ queryKey: ['bills'] })
  }

  return (
    <Card className="transition-colors">
      <CardContent className="p-0">
        {/* TOP STRIP: tabs + date */}
        <div className={cn(
          'flex items-center justify-between border-b bg-muted/30',
          compact ? 'px-2 py-0.5' : 'px-3 py-1.5',
        )}>
          <div className="flex items-center gap-0.5">
            {(['match', 'create', 'transfer', 'discuss'] as SubTab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={cn(
                  'font-medium rounded transition-colors capitalize inline-flex items-center gap-1',
                  compact ? 'px-2 py-0.5 text-[11px]' : 'px-2.5 py-1 text-xs',
                  activeTab === t
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                )}
              >
                {t}
                {t === 'match' && hasSplit && (
                  <span
                    className="w-1.5 h-1.5 rounded-full bg-matcha-500"
                    title="Possible split payment — open Match to review"
                  />
                )}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            {suggestionsLoading && (
              <span className="flex items-center gap-1 text-[11px] text-matcha-600 font-medium">
                <Loader2 className="w-3 h-3 animate-spin" />
                Analysing…
              </span>
            )}
            <span className="text-[11px] text-muted-foreground font-mono">
              {formatDate(line.date)}
            </span>
          </div>
        </div>

        {/* SPLIT */}
        <div className="grid grid-cols-1 md:grid-cols-[minmax(220px,1fr)_1fr] gap-0">
          {/* LEFT: statement line */}
          <div className={cn(
            'border-r min-w-0',
            compact ? 'px-2.5 py-1.5' : 'px-3 py-2.5',
          )}>
            <p className={cn('font-medium leading-tight break-words', compact ? 'text-xs' : 'text-sm')}>{line.description}</p>
            {line.reference && (
              <p className="text-[11px] text-muted-foreground font-mono mt-0.5">
                Ref: {line.reference}
              </p>
            )}
            <p
              className={cn(
                'font-bold font-mono',
                compact ? 'text-sm mt-0.5' : 'text-lg mt-1.5',
                isInflow ? 'text-emerald-700' : 'text-rose-700',
              )}
            >
              {isInflow ? '+' : '−'}{formatCurrency(amount, currency)}
            </p>
            <p className="text-[10px] text-muted-foreground uppercase tracking-wide mt-0.5">
              {isInflow ? 'Received' : 'Spent'}
            </p>
          </div>

          {/* RIGHT: action */}
          <div className={cn('min-w-0', compact ? 'px-2.5 py-1.5' : 'px-3 py-2.5')}>
            {activeTab === 'match' && (
              <MatchTab
                line={line}
                suggestions={suggestions ?? []}
                loading={suggestionsLoading}
                currency={currency}
                isInflow={isInflow}
                onSuccess={invalidate}
                onSwitchToCreate={() => setTab('create')}
              />
            )}
            {activeTab === 'create' && (
              <CreateTab line={line} isInflow={isInflow} currency={currency} onSuccess={invalidate} />
            )}
            {activeTab === 'transfer' && (
              <TransferTab line={line} otherAccounts={otherAccounts} onSuccess={invalidate} />
            )}
            {activeTab === 'discuss' && (
              <DiscussTab line={line} onSuccess={invalidate} />
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Match tab — compact, single primary suggestion + collapsible alternatives
// ─────────────────────────────────────────────────────────────────────────────

function MatchTab({
  line, suggestions, loading, currency, isInflow, onSuccess, onSwitchToCreate,
}: {
  line: StatementLine
  suggestions: Suggestion[]
  loading: boolean
  currency: string
  isInflow: boolean
  onSuccess: () => void
  onSwitchToCreate: () => void
}) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)
  const [explainOpen, setExplainOpen] = useState(false)
  const [bulkOpen, setBulkOpen] = useState(false)
  const confirm = useConfirm()
  const toast = useToast()
  const queryClient = useQueryClient()

  // Bulk suggestions — vendor-identified from bank description
  const { data: bulkData } = useQuery<BulkMatchData>({
    queryKey: ['bulk-suggestions', line.id],
    queryFn: () =>
      api.get(`/statement-lines/${line.id}/bulk-suggestions`).then((r) => r.data),
    staleTime: Infinity,
    gcTime: Infinity,
  })

  // Auto-select top suggestion when data arrives
  useEffect(() => {
    if (selectedKey !== null || !suggestions.length) return
    setSelectedKey(`${suggestions[0].type}-${suggestions[0].id}`)
  }, [suggestions, selectedKey])

  const selected = useMemo(
    () => suggestions.find((s) => `${s.type}-${s.id}` === selectedKey) ?? null,
    [suggestions, selectedKey],
  )

  // Only offer to learn when the engine INFERRED the match (spelling/AI). An
  // alias-exact match is already learned; a same-name match needs no alias.
  const canLearn = !!selected && (selected.method === 'fuzzy' || selected.method === 'fuzzy+embed')

  const matchMutation = useMutation({
    mutationFn: (learn: boolean) => {
      if (!selected) throw new Error('no selection')
      const endpoint =
        selected.type === 'invoice'
          ? `/statement-lines/${line.id}/match-invoice`
          : `/statement-lines/${line.id}/match-bill`
      const body =
        selected.type === 'invoice'
          ? { invoice_id: selected.id, learn_alias: learn }
          : { bill_id: selected.id, learn_alias: learn }
      return api.post(endpoint, body)
    },
    onSuccess: (_data, learn) => {
      // Reflect a newly-learned alias on the Vendor Aliases page immediately, and
      // confirm to the user that it was saved (otherwise the save is invisible).
      if (learn) {
        queryClient.invalidateQueries({ queryKey: ['aliases'] })
        toast(`Remembered “${selected?.contact_name}” for next time`)
      }
      onSuccess()
    },
  })

  // On an INFERRED match, ask via a pop-up whether to remember the vendor before
  // committing — replaces the old inline "Remember…" checkbox. "Don't ask again"
  // persists the Yes/No choice so the prompt doesn't nag on every match.
  const handleMatch = async () => {
    let learn = false
    if (canLearn) {
      learn = await confirm({
        title: 'Remember this vendor?',
        description: `Save “${line.description}” → ${selected?.contact_name} so future statements auto-match it.`,
        confirmText: 'Yes, remember',
        cancelText: 'No',
        rememberKey: 'remember-vendor',
        persistChoice: true,
      })
    }
    matchMutation.mutate(learn)
  }

  const hasBulkDocs = (bulkData?.open_docs.length ?? 0) >= 2
  const hasRegular = suggestions.length > 0

  if (loading) return <Skeleton className="h-16 w-full" />

  if (!hasRegular && !hasBulkDocs) {
    return (
      <div className="text-xs text-muted-foreground py-3 text-center">
        No matching {isInflow ? 'invoices' : 'bills'} found.{' '}
        <button onClick={onSwitchToCreate} className="text-primary hover:underline font-medium">
          Switch to Create →
        </button>
      </div>
    )
  }

  const view = selected ? viewFor(selected.score, selected.method, selected.reason) : null
  const isExact = view?.fullHighlight ?? false
  const showFieldHl = view?.fieldHighlight ?? false
  const isLow = view ? view.strength === 'weak' : false

  return (
    <div className="space-y-1">
      {/* PRIMARY suggestion — the matched invoice/bill block; turns green at ≥90%.
          The OK button lives inside the block (under the score) to save a row. */}
      {selected && view && (
        <div className={cn(
          'rounded-md border px-2.5 py-1.5 transition-colors',
          isExact ? 'border-emerald-400 bg-emerald-50' : 'border-border bg-background',
        )}>
          <div className="flex items-start justify-between gap-2.5">
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-2 flex-wrap">
                <span className="font-mono text-[11px] text-muted-foreground">{selected.label}</span>
                <span className={cn(
                  'text-sm font-medium truncate',
                  showFieldHl && view.fields.name && 'bg-emerald-100 text-emerald-900 rounded px-1',
                )}>
                  {selected.contact_name}
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
                <span className={cn(showFieldHl && view.fields.date && 'bg-emerald-100 text-emerald-900 rounded px-1')}>
                  {formatDate(selected.date)}
                </span>
                {' · '}
                <span className={cn('font-mono', showFieldHl && view.fields.amount && 'bg-emerald-100 text-emerald-900 rounded px-1')}>
                  {formatCurrency(selected.amount, currency)}
                </span>
                {' · '}
                <span>{view.reasonText}</span>
              </p>
              {isLow && (
                <p className="text-[11px] text-amber-700 mt-0.5">Low confidence — verify first</p>
              )}
            </div>
            <div className="flex flex-col items-end gap-1 flex-shrink-0">
              <ConfidenceBadge score={selected.score} method={selected.method} />
              <Button
                size="sm"
                className="h-6 px-3.5 text-xs"
                variant={isExact ? 'default' : 'outline'}
                onClick={handleMatch}
                disabled={matchMutation.isPending}
              >
                {matchMutation.isPending
                  ? <><Loader2 className="w-3 h-3 mr-1 animate-spin" />…</>
                  : 'OK'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Footer row: "more suggestions" (left) + "How was this matched?" (right)
          share ONE row to save vertical space; each expands its panel below. */}
      {(suggestions.length > 1 || selected) && (
        <div className="flex items-center justify-between gap-2">
          {suggestions.length > 1 ? (
            <button
              onClick={() => setShowAll((v) => !v)}
              className="text-[11px] text-muted-foreground hover:text-foreground flex items-center gap-1"
            >
              {showAll ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              {showAll ? 'Hide alternatives' : `${suggestions.length - 1} more suggestion${suggestions.length > 2 ? 's' : ''}`}
            </button>
          ) : (
            <span />
          )}
          {selected && (
            <button
              onClick={() => setExplainOpen((v) => !v)}
              className="text-[11px] text-muted-foreground hover:text-matcha-700 flex items-center gap-1"
            >
              How was this matched?
              {explainOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </button>
          )}
        </div>
      )}

      {showAll && (
        <div className="space-y-1 pt-0.5">
          {suggestions.slice(1).map((s) => {
            const k = `${s.type}-${s.id}`
            const altView = viewFor(s.score, s.method, s.reason)
            return (
              <button key={k} onClick={() => setSelectedKey(k)}
                className={cn(
                  'block w-full text-left rounded-md border px-2.5 py-1.5 hover:bg-muted/40 transition-colors',
                  selectedKey === k && 'border-primary ring-1 ring-primary/30',
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex items-baseline gap-1.5 text-xs">
                      <span className="font-mono text-muted-foreground">{s.label}</span>
                      <span className="truncate">{s.contact_name}</span>
                    </div>
                    <p className="text-[10px] text-muted-foreground mt-0.5">
                      <span className="font-mono">{formatCurrency(s.amount, currency)}</span> · {altView.reasonText}
                    </p>
                  </div>
                  <ConfidenceBadge score={s.score} method={s.method} small />
                </div>
              </button>
            )
          })}
        </div>
      )}

      {/* Expanded trace for the selected candidate (toggled from the footer row) */}
      {selected && explainOpen && (
        <ExplainPanel
          key={`${selected.type}-${selected.id}`}
          lineId={line.id}
          docType={selected.type}
          docId={selected.id}
        />
      )}

      {/* Bulk match disclosure */}
      {hasBulkDocs && (
        <>
          <button
            onClick={() => setBulkOpen((v) => !v)}
            className={cn(
              'w-full flex items-center justify-between text-[11px] px-2.5 py-1.5 rounded-md border transition-colors',
              bulkOpen
                ? 'bg-matcha-50 border-matcha-200 text-matcha-800 font-medium'
                : 'border-dashed border-muted-foreground/40 text-muted-foreground hover:border-matcha-300 hover:text-matcha-700',
            )}
          >
            <span className="flex items-center gap-1.5">
              {bulkData?.suggested_groups.length ? (
                <span className="w-1.5 h-1.5 rounded-full bg-matcha-500 flex-shrink-0" />
              ) : null}
              Match multiple {isInflow ? 'invoices' : 'bills'}
              {bulkData?.suggested_groups.length ? ` · ${bulkData.suggested_groups.length} group${bulkData.suggested_groups.length > 1 ? 's' : ''} found` : ''}
            </span>
            {bulkOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>

          {bulkOpen && bulkData && (
            <BulkMatchPanel
              line={line}
              data={bulkData}
              currency={currency}
              onSuccess={onSuccess}
            />
          )}
        </>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// BulkMatchPanel — Xero-style interactive multi-select with live progress bar
// ─────────────────────────────────────────────────────────────────────────────

function BulkMatchPanel({
  line, data, currency, onSuccess,
}: {
  line: StatementLine
  data: BulkMatchData
  currency: string
  onSuccess: () => void
}) {
  const target = line.received > 0 ? line.received : line.spent

  // Initialise with the first suggested group pre-selected, otherwise empty
  const [selectedIds, setSelectedIds] = useState<Set<number>>(() =>
    data.suggested_groups.length > 0
      ? new Set(data.suggested_groups[0])
      : new Set(),
  )

  const selectedDocs = data.open_docs.filter((d) => selectedIds.has(d.id))
  const selectedTotal = selectedDocs.reduce((s, d) => s + d.amount, 0)
  const diff = selectedTotal - target
  const isReady = Math.abs(diff) <= 0.01
  const isOver = diff > 0.01

  // Progress bar fill — cap at 110% to show overshoot without breaking layout
  const fillPct = Math.min((selectedTotal / target) * 100, 110)

  const barColor = isReady
    ? 'bg-emerald-500'
    : isOver
    ? 'bg-rose-500'
    : selectedTotal > 0
    ? 'bg-amber-400'
    : 'bg-slate-200'

  const toggle = (id: number) =>
    setSelectedIds((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  const bulkMutation = useMutation({
    mutationFn: () => {
      const ids = [...selectedIds]
      if (data.doc_type === 'invoice') {
        return api.post(`/statement-lines/${line.id}/match-bulk-invoices`, { invoice_ids: ids })
      }
      return api.post(`/statement-lines/${line.id}/match-bulk-bills`, { bill_ids: ids })
    },
    onSuccess,
  })

  return (
    <div className="rounded-md border border-matcha-100 bg-matcha-50/20 px-2.5 py-2 space-y-2">

      {/* Vendor chip */}
      {data.vendor && (
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] text-matcha-700 font-medium">{data.vendor}</span>
          <span className="text-[10px] text-muted-foreground">
            · {Math.round(data.vendor_score * 100)}% match from description
          </span>
        </div>
      )}

      {/* Progress bar */}
      <div className="space-y-0.5">
        <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
          <div
            className={cn('h-full rounded-full transition-all duration-200', barColor)}
            style={{ width: `${fillPct}%` }}
          />
        </div>
        <div className="flex items-center justify-between text-[11px]">
          <span className={cn(
            'font-mono font-medium',
            isReady ? 'text-emerald-700' : isOver ? 'text-rose-700' : 'text-foreground',
          )}>
            {formatCurrency(selectedTotal, currency)}
          </span>
          <span className="text-muted-foreground">
            {isReady
              ? '✓ Ready to match'
              : isOver
              ? `${formatCurrency(diff, currency)} over`
              : `${formatCurrency(target - selectedTotal, currency)} more needed`}
          </span>
        </div>
      </div>

      {/* Suggested groups — quick-pick chips */}
      {data.suggested_groups.length > 0 && (
        <div className="space-y-1">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wide">Suggested</p>
          <div className="flex flex-wrap gap-1">
            {data.suggested_groups.map((group, i) => {
              const isActive =
                group.length === selectedIds.size &&
                group.every((id) => selectedIds.has(id))
              const groupTotal = data.open_docs
                .filter((d) => group.includes(d.id))
                .reduce((s, d) => s + d.amount, 0)
              return (
                <button
                  key={i}
                  onClick={() => setSelectedIds(new Set(group))}
                  className={cn(
                    'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] border transition-colors',
                    isActive
                      ? 'bg-emerald-100 border-emerald-400 text-emerald-800 font-medium'
                      : 'bg-white border-matcha-200 text-matcha-700 hover:bg-matcha-50',
                  )}
                >
                  {group.length} {data.doc_type}s · {formatCurrency(groupTotal, currency)}
                  {isActive && ' ✓'}
                </button>
              )
            })}
          </div>
        </div>
      )}

      {/* Checkbox list */}
      <div className="space-y-0.5 max-h-40 overflow-y-auto">
        {data.open_docs.map((doc) => {
          const checked = selectedIds.has(doc.id)
          return (
            <label
              key={doc.id}
              className={cn(
                'flex items-center justify-between gap-2 px-2 py-1 rounded cursor-pointer transition-colors',
                checked ? 'bg-matcha-50' : 'hover:bg-muted/40',
              )}
            >
              <div className="flex items-center gap-2 min-w-0">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggle(doc.id)}
                  className="accent-matcha-600 w-3.5 h-3.5 flex-shrink-0"
                />
                <span className="font-mono text-[11px] text-muted-foreground">{doc.label}</span>
                <span className="text-[11px] text-muted-foreground truncate">{formatDate(doc.date)}</span>
              </div>
              <span className={cn('font-mono text-xs font-medium flex-shrink-0', checked && 'text-matcha-700')}>
                {formatCurrency(doc.amount, currency)}
              </span>
            </label>
          )
        })}
      </div>

      {/* Match button */}
      <Button
        size="sm"
        className={cn(
          'h-7 w-full text-xs transition-colors',
          isReady
            ? 'bg-emerald-600 hover:bg-emerald-700 text-white'
            : 'bg-muted text-muted-foreground cursor-not-allowed',
        )}
        onClick={() => bulkMutation.mutate()}
        disabled={!isReady || bulkMutation.isPending || selectedIds.size === 0}
      >
        {bulkMutation.isPending ? (
          <><Loader2 className="w-3 h-3 mr-1.5 animate-spin" />Matching…</>
        ) : isReady ? (
          <>Match {selectedIds.size} {data.doc_type}s · {formatCurrency(selectedTotal, currency)}</>
        ) : (
          <>Select {data.doc_type}s to match</>
        )}
      </Button>
    </div>
  )
}


// ── Confidence badge ─────────────────────────────────────────────────────────
//
// User-facing strength label ("Strong" / "Likely" / "Possible" / "Weak") with
// the numeric % shown small and quiet underneath. Method names are hidden —
// they're an engine detail.

function ConfidenceBadge({ score, method, small }: { score: number; method?: string; small?: boolean }) {
  const v = viewFor(score, method ?? '', '')
  const dot =
    v.strength === 'strong' ? 'bg-emerald-500'
    : v.strength === 'likely' ? 'bg-emerald-400'
    : v.strength === 'possible' ? 'bg-amber-400'
    : 'bg-slate-300'
  return (
    <div className={cn('flex items-center gap-1.5 flex-shrink-0', small && 'gap-1')}>
      <span className={cn('w-1.5 h-1.5 rounded-full', dot)} aria-hidden />
      <div className="text-right leading-tight">
        <p className="text-[11px] font-medium">{v.label}</p>
        {!small && (
          <p className="text-[9px] text-muted-foreground">{(score * 100).toFixed(0)}%</p>
        )}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// ExplainPanel — "How was this matched?" step-by-step trace (demo / transparency)
// ─────────────────────────────────────────────────────────────────────────────

interface TraceStep {
  n: number
  title: string
  detail: string
  [k: string]: unknown
}
interface MatchTrace {
  input: Record<string, unknown>
  steps: TraceStep[]
  final: { score: number; score_pct: number; method: string; strength: string; strength_label: string }
}

function ScoreBar({ value, className }: { value: number; className?: string }) {
  return (
    <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
      <div
        className={cn('h-full rounded-full transition-all', className ?? 'bg-matcha-500')}
        style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
      />
    </div>
  )
}

// Content-only — the parent (MatchTab) owns the open state + the trigger (in the
// footer row) and renders this panel below, full-width, only when expanded.
function ExplainPanel({ lineId, docType, docId }: { lineId: number; docType: 'invoice' | 'bill'; docId: number }) {
  const { data: trace, isLoading } = useQuery<MatchTrace>({
    queryKey: ['explain', lineId, docType, docId],
    queryFn: () =>
      api
        .get(`/statement-lines/${lineId}/explain`, { params: { doc_type: docType, doc_id: docId } })
        .then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  })

  return (
    <div className="rounded-md border bg-muted/20 p-2.5 space-y-2 text-[11px]">
      {isLoading || !trace ? (
        <div className="flex items-center gap-1.5 text-muted-foreground py-1">
          <Loader2 className="w-3 h-3 animate-spin" /> Tracing the match…
        </div>
      ) : (
        <>
          {trace.steps.map((s) => (
            <ExplainStep key={s.n} step={s} />
          ))}
          <div className="flex items-center justify-between border-t pt-1.5 mt-1">
            <span className="font-medium text-foreground">Final score</span>
            <span className="font-mono font-semibold text-matcha-700">
              {trace.final.score_pct}% · {trace.final.strength_label}
            </span>
          </div>
        </>
      )}
    </div>
  )
}

function ExplainStep({ step: s }: { step: TraceStep }) {
  const Row = ({ children }: { children: React.ReactNode }) => (
    <div className="flex items-start gap-2">
      <span className="font-mono text-muted-foreground w-3 flex-shrink-0">{s.n}</span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
  const num = (v: unknown) => (typeof v === 'number' ? v : 0)

  // Step-specific compact rendering.
  if (s.n === 1) {
    return (
      <Row>
        <p className="font-medium text-foreground">Normalise names</p>
        <p className="text-muted-foreground truncate">bank → <span className="font-mono">{String(s.bank_canonical)}</span></p>
        <p className="text-muted-foreground truncate">match → <span className="font-mono">{String(s.candidate_canonical)}</span></p>
      </Row>
    )
  }
  if (s.n === 2) {
    return (
      <Row>
        <p className="font-medium text-foreground">Known alias?</p>
        <p className="text-muted-foreground">{s.hit ? `Yes → ${String(s.resolved_to)}` : 'No learned alias'}</p>
      </Row>
    )
  }
  if (s.n === 3) {
    const m = (s.metrics as Record<string, number> | null) ?? null
    return (
      <Row>
        <p className="font-medium text-foreground">Spelling similarity</p>
        {m ? (
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-muted-foreground font-mono">
            <span>Jaro-Winkler {m.jaro_winkler.toFixed(2)}</span>
            <span>token-set {m.token_set.toFixed(2)}</span>
            <span>token-sort {m.token_sort.toFixed(2)}</span>
            <span>partial {m.partial.toFixed(2)}</span>
          </div>
        ) : <p className="text-muted-foreground">—</p>}
        <div className="flex items-center gap-2 mt-0.5">
          <ScoreBar value={num(s.composite)} className="bg-slate-400" />
          <span className="font-mono text-foreground">{num(s.composite).toFixed(2)}</span>
        </div>
      </Row>
    )
  }
  if (s.n === 4) {
    return (
      <Row>
        <p className="font-medium text-foreground">Meaning (AI embedding)</p>
        {s.fired && s.cosine != null ? (
          <div className="flex items-center gap-2">
            <ScoreBar value={num(s.cosine)} className="bg-violet-500" />
            <span className="font-mono text-foreground">{num(s.cosine).toFixed(2)}</span>
          </div>
        ) : (
          <p className="text-muted-foreground">{s.fired ? 'no signal' : 'skipped — spelling already strong'}</p>
        )}
      </Row>
    )
  }
  if (s.n === 5) {
    return (
      <Row>
        <p className="font-medium text-foreground">Best signal wins</p>
        <div className="flex items-center gap-2">
          <ScoreBar value={num(s.name_score)} className="bg-matcha-500" />
          <span className="font-mono text-foreground">{num(s.name_score).toFixed(2)}</span>
          <span className="text-muted-foreground">({String(s.method)})</span>
        </div>
      </Row>
    )
  }
  if (s.n === 6) {
    return (
      <Row>
        <p className="font-medium text-foreground">Combine: amount + date + name</p>
        <div className="text-muted-foreground font-mono space-y-0.5">
          <p>amount {num(s.amount_component).toFixed(2)} <span className="font-sans">({String(s.amount_reason)})</span></p>
          <p>date {num(s.date_component).toFixed(2)} <span className="font-sans">({String(s.date_reason)})</span></p>
          <p>name {num(s.name_component).toFixed(2)} <span className="font-sans">(raw {num(s.name_raw).toFixed(2)} × 0.30)</span></p>
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <ScoreBar value={num(s.total)} className="bg-emerald-500" />
          <span className="font-mono font-semibold text-foreground">{num(s.total).toFixed(2)}</span>
        </div>
      </Row>
    )
  }
  // Step 7
  return (
    <Row>
      <p className="font-medium text-foreground">Verdict</p>
      <p className="text-muted-foreground">
        {String(s.label)} — {s.auto_approve_quality ? 'auto-approve quality' : 'needs human review'}
      </p>
    </Row>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Create tab
// ─────────────────────────────────────────────────────────────────────────────

function CreateTab({
  line, isInflow, currency, onSuccess,
}: {
  line: StatementLine
  isInflow: boolean
  currency: string
  onSuccess: () => void
}) {
  // One "Create" category, two modes: a new journal entry, or allocating the
  // line as a credit (prepayment / overpayment).
  const [mode, setMode] = useState<'entry' | 'credit'>('entry')

  return (
    <div className="space-y-2">
      {/* Mode toggle — same segmented style as the prepayment/overpayment switch */}
      <div className="flex items-center gap-1">
        {([['entry', 'New entry'], ['credit', 'Allocate as credit']] as const).map(([m, label]) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={cn(
              'px-2.5 py-1 text-xs font-medium rounded transition-colors',
              mode === m
                ? 'bg-background text-foreground shadow-sm border'
                : 'text-muted-foreground hover:bg-muted',
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {mode === 'entry' ? (
        <CreateEntryForm line={line} isInflow={isInflow} onSuccess={onSuccess} />
      ) : (
        <CreditForm line={line} isInflow={isInflow} currency={currency} onSuccess={onSuccess} />
      )}
    </div>
  )
}

// New journal entry for a line with no document (bank fee, interest, etc.).
function CreateEntryForm({
  line, isInflow, onSuccess,
}: {
  line: StatementLine
  isInflow: boolean
  onSuccess: () => void
}) {
  const [form, setForm] = useState({
    contact_name: '',
    account_code: '',
    description: line.description,
    tax_rate: 0,
  })

  const createMutation = useMutation({
    mutationFn: () =>
      api.post(`/statement-lines/${line.id}/create-entry`, {
        contact_name: form.contact_name || null,
        account_code: form.account_code || null,
        description: form.description,
        tax_rate: form.tax_rate,
      }),
    onSuccess,
  })

  return (
    <div className="space-y-1.5">
      {/* Who | What */}
      <div className="grid grid-cols-2 gap-1.5">
        <Input
          value={form.contact_name}
          onChange={(e) => setForm((f) => ({ ...f, contact_name: e.target.value }))}
          placeholder={isInflow ? 'Payer' : 'Payee'}
          className="h-7 text-xs"
        />
        <Input
          value={form.account_code}
          onChange={(e) => setForm((f) => ({ ...f, account_code: e.target.value }))}
          placeholder="Account (e.g. 5000)"
          className="h-7 text-xs font-mono"
        />
      </div>
      {/* Why + VAT + action on a single row to save vertical space */}
      <div className="flex items-center gap-1.5">
        <Input
          value={form.description}
          onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
          placeholder="Description"
          className="h-7 text-xs flex-1 min-w-0"
        />
        <div className="flex items-center gap-1 flex-shrink-0">
          <Input
            type="number" min="0" max="100" step="1"
            value={form.tax_rate * 100}
            onChange={(e) => setForm((f) => ({ ...f, tax_rate: (parseFloat(e.target.value) || 0) / 100 }))}
            className="h-7 w-14 text-xs text-right font-mono"
            title="VAT %"
          />
          <span className="text-[11px] text-muted-foreground">%</span>
        </div>
        <Button
          size="sm"
          className="h-7 px-3 text-xs flex-shrink-0"
          onClick={() => createMutation.mutate()}
          disabled={!form.description.trim() || createMutation.isPending}
        >
          {createMutation.isPending ? (
            <><Loader2 className="w-3 h-3 mr-1 animate-spin" />Saving…</>
          ) : (
            <><Plus className="w-3 h-3 mr-1" />Create</>
          )}
        </Button>
      </div>
    </div>
  )
}

// A bill/invoice this line can PART-PAY (same vendor, bigger than the line).
// Shape mirrors the backend CreditTargetResponse from GET /partial-targets.
interface PartialTarget {
  target_type: 'invoice' | 'bill'
  id: number
  number: string | null
  contact_name: string
  total: number
  paid_amount: number
  outstanding: number
  currency: string
}

// ─────────────────────────────────────────────────────────────────────────────
// Credit form — Prepayment / Overpayment / Split (the "Allocate as credit" modes)
// ─────────────────────────────────────────────────────────────────────────────

function CreditForm({
  line, isInflow, currency, onSuccess,
}: {
  line: StatementLine
  isInflow: boolean
  currency: string
  onSuccess: () => void
}) {
  const toast = useToast()
  const qc = useQueryClient()
  const lineAmount = isInflow ? line.received : line.spent
  const docNoun = isInflow ? 'invoice' : 'bill'
  const docPath = isInflow ? 'invoices' : 'bills'

  const [mode, setMode] = useState<'prepayment' | 'overpayment' | 'split'>('prepayment')
  // Prepayment: suggest the contact from the bank line; the user confirms/edits
  // before booking (we never silently book against a blank name).
  const [contactName, setContactName] = useState(line.description ?? '')
  const [overDocId, setOverDocId] = useState<number | null>(null)
  const [splitDocId, setSplitDocId] = useState<number | null>(null)

  // Overpayment candidates: open docs the payment EXCEEDS (a surplus remains).
  const { data: docs } = useQuery<(Bill | Invoice)[]>({
    queryKey: [docPath],
    queryFn: () => api.get(`/${docPath}/`).then((r) => r.data),
    enabled: mode === 'overpayment',
  })
  const overCandidates = (docs ?? []).filter(
    (d) =>
      d.outstanding > 0.005 &&
      d.status !== 'paid' &&
      d.status !== 'voided' &&
      d.currency === currency &&
      d.outstanding < lineAmount - 0.005,
  )
  const overPicked = overCandidates.find((d) => d.id === overDocId) ?? null
  const creditAmount = overPicked
    ? Math.round((lineAmount - overPicked.outstanding) * 100) / 100
    : lineAmount

  // Split candidates: SAME-vendor open docs BIGGER than the line — backend-gated,
  // so we only ever offer a part-pay against the vendor this line names.
  const { data: splitTargets } = useQuery<PartialTarget[]>({
    queryKey: ['partial-targets', line.id],
    queryFn: () => api.get(`/statement-lines/${line.id}/partial-targets`).then((r) => r.data),
    enabled: mode === 'split',
  })
  const splitPicked = (splitTargets ?? []).find((d) => d.id === splitDocId) ?? null
  const remaining = splitPicked ? Math.round((splitPicked.outstanding - lineAmount) * 100) / 100 : 0

  const book = useMutation({
    mutationFn: () => {
      if (mode === 'split') {
        return api.post(`/statement-lines/${line.id}/match-partial`, {
          target_type: splitPicked?.target_type,
          target_id: splitDocId,
        })
      }
      return api.post(
        `/statement-lines/${line.id}/book-credit`,
        mode === 'overpayment'
          ? { kind: 'overpayment', document_ids: overDocId ? [overDocId] : [] }
          : { kind: 'prepayment', contact_name: contactName.trim() },
      )
    },
    onSuccess: () => {
      if (mode === 'split') {
        toast(`Part-paid ${formatCurrency(lineAmount, currency)} — ${formatCurrency(remaining, currency)} still owing`)
      } else {
        toast(`Booked ${mode} of ${formatCurrency(mode === 'overpayment' ? creditAmount : lineAmount, currency)}`)
      }
      qc.invalidateQueries({ queryKey: ['credits'] })
      qc.invalidateQueries({ queryKey: [docPath] })
      qc.invalidateQueries({ queryKey: ['partial-targets', line.id] })
      onSuccess()
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : 'Could not save', 'error'),
  })

  const valid =
    mode === 'prepayment'
      ? contactName.trim().length > 0
      : mode === 'overpayment'
        ? overDocId != null
        : splitDocId != null

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1">
        {(['prepayment', 'overpayment', 'split'] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={cn(
              'px-2.5 py-1 text-xs font-medium rounded capitalize transition-colors',
              mode === m
                ? 'bg-background text-foreground shadow-sm border'
                : 'text-muted-foreground hover:bg-muted',
            )}
          >
            {m}
          </button>
        ))}
      </div>

      {mode === 'prepayment' && (
        <>
          <p className="text-[11px] text-muted-foreground">
            No {docNoun} yet — hold the whole {formatCurrency(lineAmount, currency)} as a credit
            against this contact, for a future {docNoun}. Check the name before booking.
          </p>
          <Input
            value={contactName}
            onChange={(e) => setContactName(e.target.value)}
            placeholder={isInflow ? 'Customer' : 'Supplier'}
            className="h-8 text-xs"
          />
        </>
      )}

      {mode === 'overpayment' && (
        <>
          <p className="text-[11px] text-muted-foreground">
            Pick the {docNoun} this payment settles — it's paid in full and the extra becomes a credit.
          </p>
          {!overCandidates.length ? (
            <p className="text-[11px] text-muted-foreground py-2">
              No open {docNoun} smaller than {formatCurrency(lineAmount, currency)} to overpay.
            </p>
          ) : (
            <div className="space-y-1 max-h-32 overflow-y-auto">
              {overCandidates.map((d) => (
                <button
                  key={d.id}
                  onClick={() => setOverDocId(d.id)}
                  className={cn(
                    'w-full flex items-center justify-between rounded border px-2 py-1.5 text-left text-xs transition-colors',
                    overDocId === d.id ? 'border-primary bg-primary/5' : 'hover:bg-muted/40',
                  )}
                >
                  <span className="font-medium truncate">
                    {d.number ?? `${docNoun} #${d.id}`} · {d.contact_name}
                  </span>
                  <span className="font-mono text-amber-700 ml-2 shrink-0">
                    {formatCurrency(d.outstanding, d.currency)}
                  </span>
                </button>
              ))}
            </div>
          )}
          {overPicked && (
            <p className="text-[11px] text-muted-foreground">
              Credits <span className="font-medium text-foreground">{overPicked.contact_name}</span> with{' '}
              <span className="font-mono font-medium text-foreground">{formatCurrency(creditAmount, currency)}</span>.
            </p>
          )}
        </>
      )}

      {mode === 'split' && (
        <>
          <p className="text-[11px] text-muted-foreground">
            Part-pay one {docNoun} from this vendor — it stays open with the remainder,
            cleared by a later payment.
          </p>
          {!(splitTargets ?? []).length ? (
            <p className="text-[11px] text-muted-foreground py-2">
              No open {docNoun} from this contact larger than {formatCurrency(lineAmount, currency)} to part-pay.
            </p>
          ) : (
            <div className="space-y-1 max-h-32 overflow-y-auto">
              {(splitTargets ?? []).map((d) => (
                <button
                  key={d.id}
                  onClick={() => setSplitDocId(d.id)}
                  className={cn(
                    'w-full flex items-center justify-between rounded border px-2 py-1.5 text-left text-xs transition-colors',
                    splitDocId === d.id ? 'border-primary bg-primary/5' : 'hover:bg-muted/40',
                  )}
                >
                  <span className="font-medium truncate">
                    {d.number ?? `${docNoun} #${d.id}`} · {d.contact_name}
                  </span>
                  <span className="font-mono text-amber-700 ml-2 shrink-0">
                    {formatCurrency(d.outstanding, d.currency)}
                  </span>
                </button>
              ))}
            </div>
          )}
          {splitPicked && (
            <p className="text-[11px] text-muted-foreground">
              Pays <span className="font-mono font-medium text-foreground">{formatCurrency(lineAmount, currency)}</span>{' '}
              of {formatCurrency(splitPicked.outstanding, currency)} —{' '}
              <span className="font-mono font-medium text-amber-700">{formatCurrency(remaining, currency)}</span> still owing.
            </p>
          )}
        </>
      )}

      <div className="flex items-center justify-end">
        <Button
          size="sm"
          className="h-7 px-4 text-xs capitalize"
          onClick={() => book.mutate()}
          disabled={!valid || book.isPending}
        >
          {book.isPending ? (
            <><Loader2 className="w-3 h-3 mr-1 animate-spin" />Saving…</>
          ) : mode === 'split' ? (
            <>Part-pay</>
          ) : (
            <>Book {mode}</>
          )}
        </Button>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Transfer tab
// ─────────────────────────────────────────────────────────────────────────────

function TransferTab({
  line, otherAccounts, onSuccess,
}: {
  line: StatementLine
  otherAccounts: BankAccount[]
  onSuccess: () => void
}) {
  const [toAccountId, setToAccountId] = useState<number | null>(
    otherAccounts[0]?.id ?? null,
  )

  const transferMutation = useMutation({
    mutationFn: () => {
      if (!toAccountId) throw new Error('Pick an account')
      return api.post(`/statement-lines/${line.id}/transfer`, {
        to_account_id: toAccountId,
      })
    },
    onSuccess,
  })

  if (!otherAccounts.length) {
    return (
      <div className="text-xs text-muted-foreground py-3 text-center">
        Add a second bank account to enable transfers.
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2">
      <NativeSelect
        value={toAccountId ?? ''}
        onChange={(e) => setToAccountId(parseInt(e.target.value))}
        className="h-8 text-xs flex-1"
      >
        {otherAccounts.map((a) => (
          <option key={a.id} value={a.id}>
            {a.name} {a.account_number ? `(${a.account_number})` : ''}
          </option>
        ))}
      </NativeSelect>
      <Button
        size="sm"
        className="h-7 px-3 text-xs"
        onClick={() => transferMutation.mutate()}
        disabled={!toAccountId || transferMutation.isPending}
      >
        {transferMutation.isPending ? (
          <><Loader2 className="w-3 h-3 mr-1 animate-spin" />Transferring…</>
        ) : (
          <><ArrowRightLeft className="w-3 h-3 mr-1" />OK</>
        )}
      </Button>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Discuss tab
// ─────────────────────────────────────────────────────────────────────────────

function DiscussTab({
  line, onSuccess,
}: {
  line: StatementLine
  onSuccess: () => void
}) {
  const [note, setNote] = useState(line.discussion ?? '')

  const discussMutation = useMutation({
    mutationFn: () => api.post(`/statement-lines/${line.id}/discuss`, { note }),
    onSuccess,
  })

  return (
    <div className="space-y-2">
      <Textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        rows={2}
        placeholder="e.g. waiting for invoice from supplier…"
        className="text-xs"
      />
      <Button
        size="sm"
        variant="outline"
        className="h-7 px-3 text-xs"
        onClick={() => discussMutation.mutate()}
        disabled={!note.trim() || discussMutation.isPending}
      >
        {discussMutation.isPending ? (
          <><Loader2 className="w-3 h-3 mr-1 animate-spin" />Saving…</>
        ) : (
          <><MessageSquare className="w-3 h-3 mr-1" />Save Note</>
        )}
      </Button>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Reconciled tab — done items, each with what it matched to + an Unreconcile flow
// ─────────────────────────────────────────────────────────────────────────────

function ReconciledList({ accountId, currency }: { accountId: number; currency: string }) {
  const [target, setTarget] = useState<ReconciledLine | null>(null)

  // staleTime 0 so switching to this tab always shows the current set (a line just
  // reconciled on the other tab appears here immediately).
  const { data: rows, isLoading } = useQuery<ReconciledLine[]>({
    queryKey: ['reconciled', accountId],
    queryFn: () =>
      api.get(`/statement-lines/reconciled?bank_account_id=${accountId}`).then((r) => r.data),
    staleTime: 0,
  })

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-14 w-full" />)}
      </div>
    )
  }

  if (!rows?.length) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <Sparkles className="w-8 h-8 text-muted-foreground/40 mx-auto mb-3" />
          <p className="text-sm font-medium">Nothing reconciled yet</p>
          <p className="text-xs text-muted-foreground mt-1">
            Reconciled lines show up here — where you can undo any of them.
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <>
      <p className="px-1 text-xs font-medium text-muted-foreground">
        {rows.length} reconciled line{rows.length === 1 ? '' : 's'}
      </p>
      <div className="space-y-2">
        {rows.map((row) => (
          <Card key={row.id}>
            <CardContent className="flex items-center gap-3 py-2.5 px-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium">{row.description || '—'}</span>
                  <span className="whitespace-nowrap text-[10px] text-muted-foreground">
                    {formatDate(row.date)}
                  </span>
                </div>
                <p className="mt-0.5 truncate text-xs text-muted-foreground">
                  Reconciled to <span className="text-foreground">{row.target_label}</span>
                </p>
              </div>
              <span
                className={cn(
                  'whitespace-nowrap font-mono text-sm font-semibold',
                  row.direction === 'in' ? 'text-emerald-600' : 'text-foreground',
                )}
              >
                {row.direction === 'in' ? '+' : '−'}
                {formatCurrency(row.amount, currency)}
              </span>
              <Button
                size="sm"
                variant="outline"
                className="flex-shrink-0"
                onClick={() => setTarget(row)}
              >
                <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                Unreconcile
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>

      {target && (
        <UnreconcileDialog
          key={target.id}
          line={target}
          accountId={accountId}
          onClose={() => setTarget(null)}
        />
      )}
    </>
  )
}

// Confirm → visible loading → center-screen result. Reuses radix Dialog so it's
// modal, focus-trapped and centred. Cannot be dismissed mid-revert.
function UnreconcileDialog({
  line,
  accountId,
  onClose,
}: {
  line: ReconciledLine
  accountId: number
  onClose: () => void
}) {
  const queryClient = useQueryClient()

  const mut = useMutation({
    mutationFn: () =>
      api.post(`/statement-lines/${line.id}/unreconcile`).then((r) => r.data as UnreconcileResult),
    onSuccess: () => {
      // Everything that could have changed when reversing the reconciliation.
      for (const key of [
        ['reconciled', accountId], ['statement-lines'], ['suggestions'],
        ['bulk-suggestions'], ['bank-accounts'], ['aliases'], ['invoices'], ['bills'],
      ]) {
        queryClient.invalidateQueries({ queryKey: key })
      }
    },
  })

  const phase = mut.isPending ? 'loading' : mut.isSuccess ? 'done' : mut.isError ? 'error' : 'confirm'

  const tryClose = () => {
    if (!mut.isPending) onClose()  // never close mid-revert
  }

  return (
    <Dialog.Root open onOpenChange={(o) => !o && tryClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-[1px] data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <Dialog.Content
          onOpenAutoFocus={(e) => e.preventDefault()}
          onEscapeKeyDown={(e) => mut.isPending && e.preventDefault()}
          className="fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-2xl border bg-card p-6 shadow-2xl focus:outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95"
        >
          {phase === 'confirm' && (
            <>
              <div className="flex items-start gap-4">
                <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-amber-100 text-amber-600">
                  <RotateCcw className="h-5 w-5" />
                </div>
                <div className="min-w-0 flex-1 pt-0.5">
                  <Dialog.Title className="text-base font-semibold leading-6">
                    Unreconcile this transaction?
                  </Dialog.Title>
                  <Dialog.Description className="mt-1 text-sm text-muted-foreground">
                    It moves back to <span className="font-medium text-foreground">To reconcile</span> and reopens{' '}
                    <span className="font-medium text-foreground">{line.target_label}</span>. Any vendor alias this
                    match learned is removed too. Nothing is committed unless every step succeeds.
                  </Dialog.Description>
                </div>
              </div>
              <div className="mt-6 flex justify-end gap-2.5">
                <Button variant="outline" size="sm" onClick={tryClose}>Cancel</Button>
                <Button size="sm" onClick={() => mut.mutate()}>Unreconcile</Button>
              </div>
            </>
          )}

          {phase === 'loading' && (
            <div className="flex flex-col items-center justify-center gap-3 py-6 text-center">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
              <p className="text-sm font-medium">Unreconciling…</p>
              <p className="text-xs text-muted-foreground">
                Reversing the match, the balance and any learned alias.
              </p>
            </div>
          )}

          {phase === 'done' && mut.data && (
            <div className="text-center">
              <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
                <CheckCircle2 className="h-6 w-6" />
              </div>
              <Dialog.Title className="text-base font-semibold">Unreconciled</Dialog.Title>
              <div className="mt-2 space-y-1 text-sm text-muted-foreground">
                <p>Moved back to <span className="font-medium text-foreground">To reconcile</span>.</p>
                {mut.data.reverted_label && (
                  <p>Reopened <span className="font-medium text-foreground">{mut.data.reverted_label}</span>.</p>
                )}
                {mut.data.removed_alias && (
                  <p>
                    Removed learned alias{' '}
                    <span className="font-medium text-foreground">“{mut.data.removed_alias}”</span>.
                  </p>
                )}
              </div>
              <div className="mt-6 flex justify-center">
                <Button size="sm" onClick={onClose}>Done</Button>
              </div>
            </div>
          )}

          {phase === 'error' && (
            <div className="text-center">
              <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10 text-destructive">
                <AlertTriangle className="h-6 w-6" />
              </div>
              <Dialog.Title className="text-base font-semibold">Couldn’t unreconcile</Dialog.Title>
              <p className="mt-2 text-sm text-muted-foreground">
                Nothing was changed — it’s all-or-nothing. Please try again.
              </p>
              <div className="mt-6 flex justify-center gap-2.5">
                <Button variant="outline" size="sm" onClick={onClose}>Close</Button>
                <Button size="sm" onClick={() => mut.reset()}>Try again</Button>
              </div>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
