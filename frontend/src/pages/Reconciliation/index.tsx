import { useEffect, useMemo, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useIsFetching, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Check, ArrowRightLeft, MessageSquare, Plus, Sparkles,
  Landmark, Loader2, ChevronDown, ChevronUp, ArrowDownUp,
} from 'lucide-react'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { cn, formatCurrency, formatDate } from '@/lib/utils'
import { viewFor, THRESHOLDS } from '@/lib/match'
import type { BankAccount, StatementLine } from '@/types'

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
const { HIGH, MID_LOW } = THRESHOLDS

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
      <div className="space-y-4">
        <div>
          <h1 className="text-xl font-bold">Reconcile</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Select a bank account to start reconciling.
          </p>
        </div>
        {accountsLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : !accounts?.length ? (
          <Card>
            <CardContent className="py-12 text-center">
              <Landmark className="w-8 h-8 text-muted-foreground mx-auto mb-3 opacity-40" />
              <p className="text-sm text-muted-foreground">
                No bank accounts yet. Add one to start reconciling.
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {accounts.map((a) => (
              <button
                key={a.id}
                onClick={() => setSearchParams({ account: String(a.id) })}
                className="text-left"
              >
                <Card className="hover:border-primary transition-colors">
                  <CardContent className="p-3.5">
                    <div className="flex items-start justify-between mb-1.5">
                      <div className="min-w-0">
                        <p className="font-semibold text-sm truncate">{a.name}</p>
                        <p className="text-xs text-muted-foreground font-mono mt-0.5">
                          {a.bank_name && `${a.bank_name} · `}
                          {a.account_number ?? 'No number'}
                        </p>
                      </div>
                      {a.pending_count > 0 ? (
                        <Badge variant="warning">{a.pending_count} pending</Badge>
                      ) : (
                        <Badge variant="success">Reconciled</Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Diff: <span className="font-mono font-medium text-foreground">
                        {formatCurrency(a.balance_difference, a.currency)}
                      </span>
                    </p>
                  </CardContent>
                </Card>
              </button>
            ))}
          </div>
        )}
      </div>
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

  // Presentational date sort for the lines list (toggle: oldest ↔ newest). Sorts a
  // copy so we never mutate the query cache; the backend default is newest-first.
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const sortedLines = useMemo(
    () => [...lines].sort((a, b) => (sortDir === 'asc' ? 1 : -1) * a.date.localeCompare(b.date)),
    [lines, sortDir],
  )

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

      {/* Analysis progress banner — visible while suggestions are computing so
          the page never looks frozen during the matcher's (cold-start) work. */}
      {!linesLoading && total > 0 && analysing > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2.5">
          <Loader2 className="w-4 h-4 animate-spin text-indigo-600 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between mb-1">
              <p className="text-sm font-medium text-indigo-900">
                Finding matches for your transactions…
              </p>
              <span className="text-xs font-mono text-indigo-700">{done}/{total}</span>
            </div>
            <div className="h-1.5 w-full bg-indigo-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-indigo-500 rounded-full transition-all duration-300"
                style={{ width: `${pct}%` }}
              />
            </div>
            <p className="text-[11px] text-indigo-600 mt-1">
              Matching each line against open invoices and bills. The first run warms up the
              matcher, so it can take a few seconds.
            </p>
          </div>
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
          {sortedLines.map((line) => (
            <ReconcileRow
              key={line.id}
              line={line}
              accountId={accountId}
              currency={account?.currency ?? 'GBP'}
              otherAccounts={accounts.filter((a) => a.id !== accountId)}
            />
          ))}
        </div>
      )}
    </div>
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

// ─────────────────────────────────────────────────────────────────────────────
// ReconcileRow — the compact split-pane card
// ─────────────────────────────────────────────────────────────────────────────

function ReconcileRow({
  line, accountId, currency, otherAccounts,
}: {
  line: StatementLine
  accountId: number
  currency: string
  otherAccounts: BankAccount[]
}) {
  const queryClient = useQueryClient()
  const isInflow = line.received > 0
  const amount = isInflow ? line.received : line.spent

  // Fetch suggestions ONCE per row, share across tabs + tab-default logic
  const { data: suggestions, isLoading: suggestionsLoading } = useQuery<Suggestion[]>({
    queryKey: ['suggestions', line.id],
    queryFn: () => api.get(`/statement-lines/${line.id}/suggestions`).then((r) => r.data),
  })

  // Smart default tab — picked when suggestions arrive, then locked.
  // Only auto-pair side-by-side when top suggestion is confident enough (≥65%).
  // Below that, default to Create — user can still tap Match to see all options.
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

  const topScore = suggestions?.[0]?.score ?? 0
  const isExactCard = topScore >= HIGH    // whole-card green outline only at ≥90%

  return (
    <Card
      className={cn(
        'transition-colors',
        // green outline when there's an exact-quality top match AND user is on Match tab
        activeTab === 'match' && isExactCard && 'border-emerald-300',
      )}
    >
      <CardContent className="p-0">
        {/* TOP STRIP: tabs + date */}
        <div className="flex items-center justify-between px-3 py-1.5 border-b bg-muted/30">
          <div className="flex items-center gap-0.5">
            {(['match', 'create', 'transfer', 'discuss'] as SubTab[]).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={cn(
                  'px-2.5 py-1 text-xs font-medium rounded transition-colors capitalize',
                  activeTab === t
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                )}
              >
                {t}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            {suggestionsLoading && (
              <span className="flex items-center gap-1 text-[11px] text-indigo-600 font-medium">
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
          <div className="px-3 py-2.5 border-r min-w-0">
            <p className="text-sm font-medium leading-tight break-words">{line.description}</p>
            {line.reference && (
              <p className="text-[11px] text-muted-foreground font-mono mt-0.5">
                Ref: {line.reference}
              </p>
            )}
            <p
              className={cn(
                'text-lg font-bold font-mono mt-1.5',
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
          <div className="px-3 py-2.5 min-w-0">
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
              <CreateTab line={line} isInflow={isInflow} onSuccess={invalidate} />
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
  const [bulkOpen, setBulkOpen] = useState(false)
  // Self-learning: default-on for inferred matches, opt-out via the checkbox.
  const [learnAlias, setLearnAlias] = useState(true)
  const queryClient = useQueryClient()

  // Bulk suggestions — vendor-identified from bank description
  const { data: bulkData } = useQuery<BulkMatchData>({
    queryKey: ['bulk-suggestions', line.id],
    queryFn: () =>
      api.get(`/statement-lines/${line.id}/bulk-suggestions`).then((r) => r.data),
  })

  // Auto-open bulk panel if the system found an exact group
  useEffect(() => {
    if (bulkData && bulkData.suggested_groups.length > 0) {
      setBulkOpen(true)
    }
  }, [bulkData])

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
    mutationFn: () => {
      if (!selected) throw new Error('no selection')
      const endpoint =
        selected.type === 'invoice'
          ? `/statement-lines/${line.id}/match-invoice`
          : `/statement-lines/${line.id}/match-bill`
      const learn = canLearn && learnAlias
      const body =
        selected.type === 'invoice'
          ? { invoice_id: selected.id, learn_alias: learn }
          : { bill_id: selected.id, learn_alias: learn }
      return api.post(endpoint, body)
    },
    onSuccess: () => {
      // Reflect a newly-learned alias on the Vendor Aliases page immediately.
      if (canLearn && learnAlias) queryClient.invalidateQueries({ queryKey: ['aliases'] })
      onSuccess()
    },
  })

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
    <div className="space-y-1.5">
      {/* PRIMARY suggestion */}
      {selected && view && (
        <div className={cn(
          'rounded-md border px-2.5 py-2 transition-colors',
          isExact ? 'border-emerald-300 bg-emerald-50/40' : 'border-border bg-background',
        )}>
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-2 flex-wrap">
                <span className="font-mono text-[11px] text-muted-foreground">{selected.label}</span>
                <span className={cn(
                  'text-sm font-medium truncate',
                  showFieldHl && view.fields.name && 'bg-emerald-50 text-emerald-900 rounded px-1',
                )}>
                  {selected.contact_name}
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
                <span className={cn(showFieldHl && view.fields.date && 'bg-emerald-50 text-emerald-900 rounded px-1')}>
                  {formatDate(selected.date)}
                </span>
                {' · '}
                <span className={cn('font-mono', showFieldHl && view.fields.amount && 'bg-emerald-50 text-emerald-900 rounded px-1')}>
                  {formatCurrency(selected.amount, currency)}
                </span>
                {' · '}
                <span>{view.reasonText}</span>
              </p>
            </div>
            <ConfidenceBadge score={selected.score} method={selected.method} />
          </div>
        </div>
      )}

      {/* Alternatives toggle */}
      {suggestions.length > 1 && (
        <button
          onClick={() => setShowAll((v) => !v)}
          className="text-[11px] text-muted-foreground hover:text-foreground flex items-center gap-1"
        >
          {showAll ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          {showAll ? 'Hide alternatives' : `${suggestions.length - 1} more suggestion${suggestions.length > 2 ? 's' : ''}`}
        </button>
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

      {/* Self-learning opt-in — only when the engine inferred the vendor name */}
      {hasRegular && canLearn && (
        <label className="flex items-start gap-2 pt-1 text-[11px] text-muted-foreground cursor-pointer select-none">
          <input
            type="checkbox"
            checked={learnAlias}
            onChange={(e) => setLearnAlias(e.target.checked)}
            className="mt-0.5 h-3.5 w-3.5 rounded border-input accent-primary flex-shrink-0"
          />
          <span>
            Remember <span className="font-medium text-foreground">“{selected?.contact_name}”</span> for this
            description, so it auto-matches next time.
          </span>
        </label>
      )}

      {/* Single-match OK button */}
      {hasRegular && (
        <div className="flex items-center gap-2 pt-0.5">
          <Button size="sm" className="h-7 px-4 text-xs"
            variant={isExact ? 'default' : 'outline'}
            onClick={() => matchMutation.mutate()}
            disabled={!selected || matchMutation.isPending}
          >
            {matchMutation.isPending
              ? <><Loader2 className="w-3 h-3 mr-1 animate-spin" />Matching…</>
              : <>OK</>}
          </Button>
          {isLow && (
            <span className="text-[11px] text-amber-700">Low confidence — verify first</span>
          )}
        </div>
      )}

      {/* "How was this matched?" — step-by-step trace for the selected candidate */}
      {selected && (
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
                ? 'bg-indigo-50 border-indigo-200 text-indigo-800 font-medium'
                : 'border-dashed border-muted-foreground/40 text-muted-foreground hover:border-indigo-300 hover:text-indigo-700',
            )}
          >
            <span className="flex items-center gap-1.5">
              {bulkData?.suggested_groups.length ? (
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 flex-shrink-0" />
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
    <div className="rounded-md border border-indigo-100 bg-indigo-50/20 px-2.5 py-2 space-y-2">

      {/* Vendor chip */}
      {data.vendor && (
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] text-indigo-700 font-medium">{data.vendor}</span>
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
                      : 'bg-white border-indigo-200 text-indigo-700 hover:bg-indigo-50',
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
                checked ? 'bg-indigo-50' : 'hover:bg-muted/40',
              )}
            >
              <div className="flex items-center gap-2 min-w-0">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggle(doc.id)}
                  className="accent-indigo-600 w-3.5 h-3.5 flex-shrink-0"
                />
                <span className="font-mono text-[11px] text-muted-foreground">{doc.label}</span>
                <span className="text-[11px] text-muted-foreground truncate">{formatDate(doc.date)}</span>
              </div>
              <span className={cn('font-mono text-xs font-medium flex-shrink-0', checked && 'text-indigo-700')}>
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
        className={cn('h-full rounded-full transition-all', className ?? 'bg-indigo-500')}
        style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
      />
    </div>
  )
}

function ExplainPanel({ lineId, docType, docId }: { lineId: number; docType: 'invoice' | 'bill'; docId: number }) {
  const [open, setOpen] = useState(false)

  const { data: trace, isLoading } = useQuery<MatchTrace>({
    queryKey: ['explain', lineId, docType, docId],
    queryFn: () =>
      api
        .get(`/statement-lines/${lineId}/explain`, { params: { doc_type: docType, doc_id: docId } })
        .then((r) => r.data),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  })

  return (
    <div className="pt-0.5">
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-[11px] text-muted-foreground hover:text-indigo-700 flex items-center gap-1"
      >
        {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        How was this matched?
      </button>

      {open && (
        <div className="mt-1.5 rounded-md border bg-muted/20 p-2.5 space-y-2 text-[11px]">
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
                <span className="font-mono font-semibold text-indigo-700">
                  {trace.final.score_pct}% · {trace.final.strength_label}
                </span>
              </div>
            </>
          )}
        </div>
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
          <ScoreBar value={num(s.name_score)} className="bg-indigo-500" />
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
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <Input
          value={form.contact_name}
          onChange={(e) => setForm((f) => ({ ...f, contact_name: e.target.value }))}
          placeholder={isInflow ? 'Payer' : 'Payee'}
          className="h-8 text-xs"
        />
        <Input
          value={form.account_code}
          onChange={(e) => setForm((f) => ({ ...f, account_code: e.target.value }))}
          placeholder="Account (e.g. 5000)"
          className="h-8 text-xs font-mono"
        />
      </div>
      <Input
        value={form.description}
        onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
        placeholder="Description"
        className="h-8 text-xs"
      />
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] text-muted-foreground">VAT</span>
          <Input
            type="number" min="0" max="100" step="1"
            value={form.tax_rate * 100}
            onChange={(e) => setForm((f) => ({ ...f, tax_rate: (parseFloat(e.target.value) || 0) / 100 }))}
            className="h-7 w-16 text-xs text-right font-mono"
          />
          <span className="text-[11px] text-muted-foreground">%</span>
        </div>
        <Button
          size="sm"
          className="h-7 px-4 text-xs ml-auto"
          onClick={() => createMutation.mutate()}
          disabled={!form.description.trim() || createMutation.isPending}
        >
          {createMutation.isPending ? (
            <><Loader2 className="w-3 h-3 mr-1 animate-spin" />Saving…</>
          ) : (
            <><Plus className="w-3 h-3 mr-1" />Create & Reconcile</>
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
