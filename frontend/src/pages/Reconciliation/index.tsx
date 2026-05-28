import { useEffect, useMemo, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Check, ArrowRightLeft, MessageSquare, Plus, Sparkles,
  Landmark, Loader2, ChevronDown, ChevronUp,
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
          {lines.map((line) => (
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
          <span className="text-[11px] text-muted-foreground font-mono">
            {formatDate(line.date)}
          </span>
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

  // Auto-select top suggestion when data arrives
  useEffect(() => {
    if (selectedKey !== null || !suggestions.length) return
    const top = suggestions[0]
    setSelectedKey(`${top.type}-${top.id}`)
  }, [suggestions, selectedKey])

  const selected = useMemo(
    () => suggestions.find((s) => `${s.type}-${s.id}` === selectedKey) ?? null,
    [suggestions, selectedKey],
  )

  const matchMutation = useMutation({
    mutationFn: () => {
      if (!selected) throw new Error('no selection')
      const endpoint =
        selected.type === 'invoice'
          ? `/statement-lines/${line.id}/match-invoice`
          : `/statement-lines/${line.id}/match-bill`
      const body =
        selected.type === 'invoice'
          ? { invoice_id: selected.id }
          : { bill_id: selected.id }
      return api.post(endpoint, body)
    },
    onSuccess,
  })

  if (loading) {
    return <Skeleton className="h-16 w-full" />
  }

  if (!suggestions.length) {
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
      {/* PRIMARY suggestion card */}
      {selected && view && (
        <div
          className={cn(
            'rounded-md border px-2.5 py-2 transition-colors',
            isExact ? 'border-emerald-300 bg-emerald-50/40' : 'border-border bg-background',
          )}
        >
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-2 flex-wrap">
                <span className="font-mono text-[11px] text-muted-foreground">{selected.label}</span>
                <span
                  className={cn(
                    'text-sm font-medium truncate',
                    showFieldHl && view.fields.name &&
                      'bg-emerald-50 text-emerald-900 rounded px-1',
                  )}
                >
                  {selected.contact_name}
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
                <span
                  className={cn(
                    showFieldHl && view.fields.date &&
                      'bg-emerald-50 text-emerald-900 rounded px-1',
                  )}
                >
                  {formatDate(selected.date)}
                </span>
                {' · '}
                <span
                  className={cn(
                    'font-mono',
                    showFieldHl && view.fields.amount &&
                      'bg-emerald-50 text-emerald-900 rounded px-1',
                  )}
                >
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
          {showAll ? 'Hide alternatives' : `Show ${suggestions.length - 1} more`}
        </button>
      )}

      {/* Alternatives list */}
      {showAll && (
        <div className="space-y-1 pt-1">
          {suggestions.slice(1).map((s) => {
            const k = `${s.type}-${s.id}`
            const altView = viewFor(s.score, s.method, s.reason)
            return (
              <button
                key={k}
                onClick={() => setSelectedKey(k)}
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

      {/* OK */}
      <div className="flex items-center gap-2 pt-1">
        <Button
          size="sm"
          className="h-7 px-4 text-xs"
          variant={isExact ? 'default' : 'outline'}
          onClick={() => matchMutation.mutate()}
          disabled={!selected || matchMutation.isPending}
        >
          {matchMutation.isPending ? (
            <><Loader2 className="w-3 h-3 mr-1 animate-spin" />Matching…</>
          ) : (
            <>OK</>
          )}
        </Button>
        {isLow && (
          <span className="text-[11px] text-amber-700">
            Low confidence — verify before approving
          </span>
        )}
      </div>
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
