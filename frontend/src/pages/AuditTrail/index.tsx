import { useEffect, useMemo, useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import {
  Download, Search, ChevronLeft, ChevronRight, ChevronDown,
  Receipt, FileText, Layers, PlusCircle, ArrowRightLeft, MessageSquare, Undo2,
  ScrollText, Clock, X, ArrowDownLeft, ArrowUpRight, Activity, CheckCircle2,
} from 'lucide-react'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { PageHeader } from '@/components/ui/page-header'
import { StatStrip } from '@/components/ui/stat-strip'
import { cn, formatCurrency } from '@/lib/utils'

const PAGE_SIZE = 50

// ── Types (mirror the /audit API) ─────────────────────────────────────────────

interface AuditEvent {
  id: number
  created_at: string
  actor_name: string
  action: string
  statement_line_id: number | null
  bank_account_id: number | null
  line_date: string | null
  line_description: string
  amount: number
  currency: string
  target_type: string | null
  target_id: number | null
  target_label: string
  method: string | null
  score: number | null
  detail: string
}

interface AuditSummary {
  total: number
  by_action: Record<string, number>
  accounts: { id: number; name: string }[]
  first_at: string | null
  last_at: string | null
}

type BadgeVariant = 'success' | 'warning' | 'destructive' | 'info' | 'muted' | 'secondary'

const ACTION_META: Record<string, { label: string; variant: BadgeVariant; icon: React.ElementType }> = {
  match_invoice: { label: 'Matched invoice', variant: 'success', icon: Receipt },
  match_bill: { label: 'Matched bill', variant: 'success', icon: FileText },
  match_bulk_invoices: { label: 'Matched invoices (split)', variant: 'success', icon: Layers },
  match_bulk_bills: { label: 'Matched bills (split)', variant: 'success', icon: Layers },
  create_entry: { label: 'Created entry', variant: 'info', icon: PlusCircle },
  transfer: { label: 'Transfer', variant: 'info', icon: ArrowRightLeft },
  discuss: { label: 'Note', variant: 'warning', icon: MessageSquare },
  unreconcile: { label: 'Unreconciled', variant: 'destructive', icon: Undo2 },
}

function actionMeta(a: string) {
  return ACTION_META[a] ?? { label: a.replace(/_/g, ' '), variant: 'muted' as BadgeVariant, icon: Activity }
}

const ACTION_ORDER = Object.keys(ACTION_META)

function formatDateTime(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso.slice(0, 16).replace('T', ' ')
  return d.toLocaleString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function formatDay(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso.slice(0, 10)
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function AuditTrail() {
  const [qInput, setQInput] = useState('')
  const [q, setQ] = useState('')
  const [action, setAction] = useState('')
  const [accountId, setAccountId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [page, setPage] = useState(0)
  const [openId, setOpenId] = useState<number | null>(null)

  // Debounce the free-text search so we don't fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => setQ(qInput), 300)
    return () => clearTimeout(t)
  }, [qInput])

  // Any filter change resets to the first page.
  useEffect(() => { setPage(0) }, [q, action, accountId, dateFrom, dateTo])

  const filterParams = useMemo(() => {
    const p: Record<string, string> = {}
    if (action) p.action = action
    if (accountId) p.bank_account_id = accountId
    if (q) p.q = q
    if (dateFrom) p.date_from = dateFrom
    if (dateTo) p.date_to = dateTo
    return p
  }, [action, accountId, q, dateFrom, dateTo])

  const hasFilters = Boolean(q || action || accountId || dateFrom || dateTo)

  const { data: summary } = useQuery<AuditSummary>({
    queryKey: ['audit', 'summary'],
    queryFn: () => api.get('/audit/summary').then((r) => r.data),
  })

  const { data: events, isLoading, isFetching } = useQuery<AuditEvent[]>({
    queryKey: ['audit', 'list', filterParams, page],
    queryFn: () =>
      api.get('/audit/', { params: { ...filterParams, skip: page * PAGE_SIZE, limit: PAGE_SIZE } })
        .then((r) => r.data),
    placeholderData: keepPreviousData,
  })

  const rows = events ?? []
  const hasNext = rows.length === PAGE_SIZE
  const hasPrev = page > 0

  function clearFilters() {
    setQInput(''); setQ(''); setAction(''); setAccountId(''); setDateFrom(''); setDateTo('')
  }

  function handleExport() {
    const p = new URLSearchParams(filterParams)
    window.open(`/api/v1/audit/export?${p.toString()}`, '_blank')
  }

  // KPI groupings derived from the summary's by_action counts.
  const counts = summary?.by_action ?? {}
  const sum = (...keys: string[]) => keys.reduce((n, k) => n + (counts[k] ?? 0), 0)
  const matched = sum('match_invoice', 'match_bill', 'match_bulk_invoices', 'match_bulk_bills')
  const reversed = sum('unreconcile')
  const adjustments = sum('create_entry', 'transfer', 'discuss')

  return (
    <div className="space-y-5 animate-in fade-in-0 duration-300">
      <PageHeader
        icon={ScrollText}
        title="Audit Trail"
        subtitle="An immutable record of every reconciliation decision — who did what, when, and why."
        actions={
          <Button variant="outline" size="sm" onClick={handleExport} disabled={!summary?.total}>
            <Download className="w-4 h-4 mr-1.5" />
            Export CSV
          </Button>
        }
      />

      <StatStrip
        stats={[
          { label: 'Total events', value: summary?.total ?? 0, icon: Activity, accent: (summary?.total ?? 0) > 0 },
          { label: 'Matches', value: matched, icon: CheckCircle2 },
          { label: 'Reversals', value: reversed, icon: Undo2 },
          { label: 'Last activity', value: summary?.last_at ? formatDay(summary.last_at) : '—', icon: Clock,
            sub: adjustments > 0 ? `${adjustments} adjustments` : undefined },
        ]}
      />

      {/* Filter bar */}
      <Card>
        <CardContent className="p-4">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex-1 min-w-[200px] space-y-1">
              <label className="text-[11px] font-medium text-muted-foreground">Search</label>
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  value={qInput}
                  onChange={(e) => setQInput(e.target.value)}
                  placeholder="Description, vendor, person, note…"
                  className="pl-8"
                />
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-[11px] font-medium text-muted-foreground">Action</label>
              <NativeSelect value={action} onChange={(e) => setAction(e.target.value)} className="w-44">
                <option value="">All actions</option>
                {ACTION_ORDER.map((a) => (
                  <option key={a} value={a}>{actionMeta(a).label}</option>
                ))}
              </NativeSelect>
            </div>
            <div className="space-y-1">
              <label className="text-[11px] font-medium text-muted-foreground">Account</label>
              <NativeSelect value={accountId} onChange={(e) => setAccountId(e.target.value)} className="w-44">
                <option value="">All accounts</option>
                {summary?.accounts.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </NativeSelect>
            </div>
            <div className="space-y-1">
              <label className="text-[11px] font-medium text-muted-foreground">From</label>
              <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="w-40" />
            </div>
            <div className="space-y-1">
              <label className="text-[11px] font-medium text-muted-foreground">To</label>
              <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="w-40" />
            </div>
            {hasFilters && (
              <Button variant="ghost" size="sm" onClick={clearFilters} className="text-muted-foreground">
                <X className="w-4 h-4 mr-1" /> Clear
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Events table */}
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-4 space-y-2">
              {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}
            </div>
          ) : rows.length === 0 ? (
            <div className="py-16 text-center">
              <ScrollText className="w-9 h-9 text-muted-foreground/40 mx-auto mb-3" />
              <p className="text-sm font-medium text-foreground">
                {hasFilters ? 'No events match these filters' : 'No reconciliation activity yet'}
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                {hasFilters
                  ? 'Try widening your search or clearing the filters.'
                  : 'Once you match lines on the Reconcile screen, every action is recorded here.'}
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/40 text-[11px] uppercase tracking-wider text-muted-foreground">
                    <th className="text-left font-semibold px-4 py-2.5 whitespace-nowrap">When</th>
                    <th className="text-left font-semibold px-4 py-2.5">Action</th>
                    <th className="text-left font-semibold px-4 py-2.5">Transaction</th>
                    <th className="text-left font-semibold px-4 py-2.5">Target</th>
                    <th className="text-left font-semibold px-4 py-2.5 whitespace-nowrap">By</th>
                    <th className="w-8" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/60">
                  {rows.map((e) => (
                    <EventRow key={e.id} e={e} open={openId === e.id}
                      onToggle={() => setOpenId(openId === e.id ? null : e.id)} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Pagination */}
      {(hasPrev || hasNext) && (
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            Page {page + 1} · showing {rows.length} event{rows.length === 1 ? '' : 's'}
            {isFetching && ' · updating…'}
          </span>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => setPage((p) => p - 1)} disabled={!hasPrev}>
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <Button size="sm" variant="outline" onClick={() => setPage((p) => p + 1)} disabled={!hasNext}>
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Pieces ────────────────────────────────────────────────────────────────

function EventRow({ e, open, onToggle }: { e: AuditEvent; open: boolean; onToggle: () => void }) {
  const meta = actionMeta(e.action)
  const Icon = meta.icon
  const inflow = e.amount >= 0

  return (
    <>
      <tr className="hover:bg-muted/30 transition-colors cursor-pointer" onClick={onToggle}>
        <td className="px-4 py-3 whitespace-nowrap align-top">
          <span className="font-mono text-xs text-muted-foreground">{formatDateTime(e.created_at)}</span>
        </td>
        <td className="px-4 py-3 align-top">
          <Badge variant={meta.variant}>
            <Icon className="w-3 h-3 mr-1" />
            {meta.label}
          </Badge>
        </td>
        <td className="px-4 py-3 align-top min-w-[220px]">
          <p className="font-medium text-foreground truncate max-w-[280px]">{e.line_description || '—'}</p>
          <p className="text-[11px] text-muted-foreground mt-0.5 flex items-center gap-1.5">
            <span>{formatDay(e.line_date)}</span>
            {e.amount !== 0 && (
              <span className={cn('inline-flex items-center gap-0.5 font-mono', inflow ? 'text-success' : 'text-foreground')}>
                {inflow ? <ArrowDownLeft className="w-3 h-3" /> : <ArrowUpRight className="w-3 h-3" />}
                {inflow ? '+' : '−'}{formatCurrency(Math.abs(e.amount), e.currency)}
              </span>
            )}
          </p>
        </td>
        <td className="px-4 py-3 align-top">
          <span className="text-foreground">{e.target_label || '—'}</span>
        </td>
        <td className="px-4 py-3 align-top whitespace-nowrap text-muted-foreground">{e.actor_name || '—'}</td>
        <td className="px-2 py-3 align-top text-muted-foreground">
          <ChevronDown className={cn('w-4 h-4 transition-transform', open && 'rotate-180')} />
        </td>
      </tr>
      {open && (
        <tr className="bg-muted/20">
          <td colSpan={6} className="px-4 py-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-2 text-xs">
              <Detail label="Detail" value={e.detail || '—'} wide />
              {e.method && <Detail label="Method" value={e.method} />}
              {e.score != null && <Detail label="Confidence" value={`${Math.round(e.score * 100)}%`} />}
              {e.statement_line_id != null && <Detail label="Statement line" value={`#${e.statement_line_id}`} />}
              {e.target_type && e.target_type !== 'none' && (
                <Detail label="Target" value={`${e.target_type}${e.target_id != null ? ` #${e.target_id}` : ''}`} />
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

function Detail({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={cn(wide && 'sm:col-span-2 lg:col-span-2')}>
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="text-foreground mt-0.5 break-words">{value}</p>
    </div>
  )
}
