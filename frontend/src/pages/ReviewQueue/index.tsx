/**
 * Exceptions — cross-cutting reconciliation jobs that don't fit the
 * line-by-line Reconcile screen.
 *
 *   • Bulk Approve — top match per pending line across ALL accounts,
 *                    multi-select, one button approves the lot.
 *   • Duplicates   — pairs of invoices/bills that look like the same
 *                    document (same amount, near date, similar name).
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle, Check, Sparkles, Loader2, Layers, Copy, Trash2,
} from 'lucide-react'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn, formatCurrency, formatDate } from '@/lib/utils'
import { viewFor, strengthFor } from '@/lib/match'

type Tab = 'bulk' | 'duplicates'

// ─── Types from API ──────────────────────────────────────────────────────────

interface BulkItem {
  line: {
    id: number
    bank_account_id: number
    bank_account_name: string
    date: string
    description: string
    spent: number
    received: number
    currency: string
  }
  candidate: {
    type: 'invoice' | 'bill'
    id: number
    label: string
    contact_name: string
    date: string
    amount: number
  }
  score: number
  method: string
  reason: string
}

interface DuplicatePair {
  kind: 'invoice' | 'bill'
  left: { id: number; label: string; contact_name: string; date: string; amount: number; status: string }
  right: { id: number; label: string; contact_name: string; date: string; amount: number; status: string }
  name_similarity: number
  days_apart: number
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function Exceptions() {
  const [tab, setTab] = useState<Tab>('bulk')

  const { data: bulk } = useQuery<BulkItem[]>({
    queryKey: ['exceptions', 'bulk-approve-queue'],
    queryFn: () => api.get('/exceptions/bulk-approve-queue', { params: { min_score: 0.65 } }).then((r) => r.data),
  })

  const { data: dupes } = useQuery<DuplicatePair[]>({
    queryKey: ['exceptions', 'duplicates'],
    queryFn: () => api.get('/exceptions/duplicates').then((r) => r.data),
  })

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Exceptions</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Cross-cutting items that need attention — bulk approvals, duplicates,
          and other things that don't fit the line-by-line reconcile flow.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex items-center border-b">
        <TabButton active={tab === 'bulk'} count={bulk?.length} onClick={() => setTab('bulk')}>
          <Layers className="w-3.5 h-3.5 mr-1.5" />
          Bulk approve
        </TabButton>
        <TabButton active={tab === 'duplicates'} count={dupes?.length} onClick={() => setTab('duplicates')}>
          <Copy className="w-3.5 h-3.5 mr-1.5" />
          Duplicates
        </TabButton>
      </div>

      {tab === 'bulk' && <BulkApproveTab items={bulk} />}
      {tab === 'duplicates' && <DuplicatesTab pairs={dupes} />}
    </div>
  )
}

function TabButton({
  active, count, onClick, children,
}: {
  active: boolean
  count: number | undefined
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'flex items-center px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors',
        active
          ? 'border-primary text-foreground'
          : 'border-transparent text-muted-foreground hover:text-foreground',
      )}
    >
      {children}
      {count !== undefined && count > 0 && (
        <span
          className={cn(
            'ml-2 text-[11px] px-1.5 py-0.5 rounded-full font-mono',
            active ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground',
          )}
        >
          {count}
        </span>
      )}
    </button>
  )
}

// ─── Bulk approve tab ────────────────────────────────────────────────────────

function BulkApproveTab({ items }: { items: BulkItem[] | undefined }) {
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [running, setRunning] = useState(false)

  if (items === undefined) {
    return <Skeleton className="h-48 w-full" />
  }
  if (!items.length) {
    return <EmptyState
      icon={Sparkles}
      title="No bulk-approval candidates"
      body="Either nothing pending, or no suggestion exceeds the 65% threshold. Use the Reconcile screen for harder cases."
    />
  }

  const allSelected = selected.size === items.length
  const someSelected = selected.size > 0

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  const toggleAll = () => {
    if (allSelected) setSelected(new Set())
    else setSelected(new Set(items.map((i) => i.line.id)))
  }

  const approveSelected = async () => {
    setRunning(true)
    const toApply = items.filter((i) => selected.has(i.line.id))
    for (const item of toApply) {
      const url =
        item.candidate.type === 'invoice'
          ? `/statement-lines/${item.line.id}/match-invoice`
          : `/statement-lines/${item.line.id}/match-bill`
      const body =
        item.candidate.type === 'invoice'
          ? { invoice_id: item.candidate.id }
          : { bill_id: item.candidate.id }
      try {
        await api.post(url, body)
      } catch {
        // continue with the rest; bad ones stay pending
      }
    }
    setSelected(new Set())
    setRunning(false)
    queryClient.invalidateQueries({ queryKey: ['exceptions'] })
    queryClient.invalidateQueries({ queryKey: ['statement-lines'] })
    queryClient.invalidateQueries({ queryKey: ['bank-accounts'] })
  }

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          {someSelected
            ? `${selected.size} selected`
            : `${items.length} candidate${items.length === 1 ? '' : 's'} ready to approve`}
        </p>
        {someSelected && (
          <Button size="sm" onClick={approveSelected} disabled={running}>
            {running ? (
              <><Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />Approving…</>
            ) : (
              <><Check className="w-3.5 h-3.5 mr-1.5" />Approve {selected.size} selected</>
            )}
          </Button>
        )}
      </div>

      <Card>
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/30">
                <th className="px-3 py-2 text-left">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={toggleAll}
                    className="w-4 h-4 accent-primary cursor-pointer"
                  />
                </th>
                <Th>Account</Th>
                <Th>Bank line</Th>
                <Th right>Amount</Th>
                <Th>Matches</Th>
                <Th right>Date</Th>
                <Th>Strength</Th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const isSel = selected.has(item.line.id)
                const isInflow = item.line.received > 0
                const amount = isInflow ? item.line.received : item.line.spent
                const v = viewFor(item.score, item.method, item.reason)
                return (
                  <tr
                    key={item.line.id}
                    onClick={() => toggle(item.line.id)}
                    className={cn(
                      'border-b last:border-0 cursor-pointer transition-colors',
                      isSel ? 'bg-primary/5' : 'hover:bg-muted/30',
                    )}
                  >
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={isSel}
                        onChange={() => toggle(item.line.id)}
                        onClick={(e) => e.stopPropagation()}
                        className="w-4 h-4 accent-primary cursor-pointer"
                      />
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground truncate max-w-[140px]">
                      {item.line.bank_account_name}
                    </td>
                    <td className="px-3 py-2 min-w-0">
                      <p className="text-sm font-medium truncate max-w-[220px]">{item.line.description}</p>
                      <p className="text-[11px] text-muted-foreground">{formatDate(item.line.date)}</p>
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      <span className={isInflow ? 'text-emerald-700' : 'text-rose-700'}>
                        {isInflow ? '+' : '−'}{formatCurrency(amount, item.line.currency)}
                      </span>
                    </td>
                    <td className="px-3 py-2 min-w-0">
                      <p className="text-sm truncate max-w-[200px]">
                        <span className="font-mono text-[11px] text-muted-foreground mr-1.5">
                          {item.candidate.label}
                        </span>
                        {item.candidate.contact_name}
                      </p>
                      <p className="text-[11px] text-muted-foreground">{v.reasonText}</p>
                    </td>
                    <td className="px-3 py-2 text-right text-xs text-muted-foreground whitespace-nowrap">
                      {formatDate(item.candidate.date)}
                    </td>
                    <td className="px-3 py-2">
                      <StrengthIndicator score={item.score} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}

// ─── Duplicates tab ──────────────────────────────────────────────────────────

function DuplicatesTab({ pairs }: { pairs: DuplicatePair[] | undefined }) {
  const queryClient = useQueryClient()
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())

  const deleteMutation = useMutation({
    mutationFn: ({ kind, id }: { kind: 'invoice' | 'bill'; id: number }) =>
      api.delete(`/${kind === 'invoice' ? 'invoices' : 'bills'}/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['exceptions'] })
      queryClient.invalidateQueries({ queryKey: ['invoices'] })
      queryClient.invalidateQueries({ queryKey: ['bills'] })
    },
  })

  if (pairs === undefined) {
    return <Skeleton className="h-48 w-full" />
  }
  const visible = pairs.filter(
    (p) => !dismissed.has(`${p.kind}-${p.left.id}-${p.right.id}`),
  )
  if (!visible.length) {
    return <EmptyState
      icon={Sparkles}
      title="No suspected duplicates"
      body="Same amount, similar name, dates within 30 days — nothing matches."
    />
  }

  return (
    <div className="space-y-2">
      {visible.map((p) => {
        const k = `${p.kind}-${p.left.id}-${p.right.id}`
        return (
          <Card key={k}>
            <CardContent className="p-3">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-600 flex-shrink-0" />
                <p className="text-sm font-medium">
                  Two {p.kind}s look like the same document
                </p>
                <Badge variant="muted" className="ml-auto">
                  {p.days_apart}d apart · {(p.name_similarity * 100).toFixed(0)}% name match
                </Badge>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <DocCard
                  doc={p.left}
                  onDelete={() => deleteMutation.mutate({ kind: p.kind, id: p.left.id })}
                  deleting={deleteMutation.isPending}
                />
                <DocCard
                  doc={p.right}
                  onDelete={() => deleteMutation.mutate({ kind: p.kind, id: p.right.id })}
                  deleting={deleteMutation.isPending}
                />
              </div>
              <div className="mt-2 flex justify-end">
                <button
                  onClick={() => setDismissed((d) => new Set([...d, k]))}
                  className="text-xs text-muted-foreground hover:text-foreground"
                >
                  Not a duplicate · dismiss
                </button>
              </div>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}

function DocCard({
  doc, onDelete, deleting,
}: {
  doc: DuplicatePair['left']
  onDelete: () => void
  deleting: boolean
}) {
  return (
    <div className="border rounded-md p-2.5">
      <div className="flex items-start justify-between gap-2 mb-1">
        <div className="min-w-0">
          <p className="font-mono text-[11px] text-muted-foreground">{doc.label}</p>
          <p className="text-sm font-medium truncate">{doc.contact_name}</p>
        </div>
        <Badge variant="muted" className="flex-shrink-0 capitalize">{doc.status.replace('_', ' ')}</Badge>
      </div>
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{formatDate(doc.date)}</span>
        <span className="font-mono font-medium text-foreground">
          {formatCurrency(doc.amount)}
        </span>
      </div>
      <Button
        size="sm"
        variant="outline"
        className="h-7 text-xs mt-2 w-full text-rose-600 border-rose-200 hover:bg-rose-50"
        onClick={onDelete}
        disabled={deleting}
      >
        <Trash2 className="w-3 h-3 mr-1.5" />
        Delete this one
      </Button>
    </div>
  )
}

// ─── Bits ────────────────────────────────────────────────────────────────────

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <th
      className={cn(
        'px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground',
        right ? 'text-right' : 'text-left',
      )}
    >
      {children}
    </th>
  )
}

function StrengthIndicator({ score }: { score: number }) {
  const s = strengthFor(score)
  const dot =
    s.strength === 'strong' ? 'bg-emerald-500'
    : s.strength === 'likely' ? 'bg-emerald-400'
    : s.strength === 'possible' ? 'bg-amber-400'
    : 'bg-slate-300'
  return (
    <div className="flex items-center gap-1.5">
      <span className={cn('w-1.5 h-1.5 rounded-full', dot)} aria-hidden />
      <span className="text-xs">{s.label}</span>
    </div>
  )
}

function EmptyState({
  icon: Icon, title, body,
}: {
  icon: typeof Sparkles
  title: string
  body: string
}) {
  return (
    <Card>
      <CardContent className="py-12 text-center">
        <Icon className="w-8 h-8 text-muted-foreground mx-auto mb-3 opacity-40" />
        <p className="text-sm font-medium">{title}</p>
        <p className="text-xs text-muted-foreground mt-1 max-w-md mx-auto">{body}</p>
      </CardContent>
    </Card>
  )
}
