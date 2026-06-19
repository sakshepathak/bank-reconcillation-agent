import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, X } from 'lucide-react'
import { api, ApiError } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useToast } from '@/components/ToastProvider'
import { cn, formatCurrency, formatDate } from '@/lib/utils'
import type { Credit, CreditDirection, CreditTarget } from '@/types'

const KIND_LABEL: Record<Credit['kind'], string> = {
  overpayment: 'Overpayment',
  prepayment: 'Prepayment',
}

/**
 * Lists held credits (overpayments & prepayments) for one direction and lets the
 * user apply outstanding credit to an open bill/invoice — Xero's "Allocate
 * outstanding credit" flow. Surfaced as a sub-tab inside Purchases (payable) and
 * Sales (receivable). Credits are booked on the Reconcile screen, not here.
 */
export function CreditsList({ direction }: { direction: CreditDirection }) {
  const [allocating, setAllocating] = useState<Credit | null>(null)
  const noun = direction === 'payable' ? 'supplier' : 'customer'
  const docNoun = direction === 'payable' ? 'bill' : 'invoice'

  const { data: credits, isLoading } = useQuery<Credit[]>({
    queryKey: ['credits', direction],
    queryFn: () => api.get(`/credits/?direction=${direction}`).then((r) => r.data),
  })

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}
      </div>
    )
  }

  if (!credits?.length) {
    return (
      <Card>
        <CardContent className="py-16 text-center text-sm text-muted-foreground">
          No overpayments or prepayments yet. They’re created on the Reconcile screen when a
          payment doesn’t line up with a {docNoun}.
        </CardContent>
      </Card>
    )
  }

  return (
    <>
      <Card>
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/40">
                <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground capitalize">{noun}</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">Type</th>
                <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">Date</th>
                <th className="px-4 py-2.5 text-right text-xs font-semibold text-muted-foreground">Original</th>
                <th className="px-4 py-2.5 text-right text-xs font-semibold text-muted-foreground">Remaining</th>
                <th className="px-4 py-2.5 text-center text-xs font-semibold text-muted-foreground">Status</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {credits.map((c) => (
                <tr key={c.id} className="border-b last:border-0 hover:bg-muted/30 transition-colors">
                  <td className="px-4 py-2.5 font-medium">{c.contact_name}</td>
                  <td className="px-4 py-2.5"><Badge variant="info">{KIND_LABEL[c.kind]}</Badge></td>
                  <td className="px-4 py-2.5 text-xs whitespace-nowrap">{formatDate(c.issue_date)}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-sm">{formatCurrency(c.original_amount, c.currency)}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-sm">
                    {c.outstanding > 0.005 ? (
                      <span className="text-emerald-700 font-medium">{formatCurrency(c.outstanding, c.currency)}</span>
                    ) : (
                      <span className="text-muted-foreground">{formatCurrency(0, c.currency)}</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    <Badge variant={c.status === 'paid' ? 'muted' : c.status === 'voided' ? 'destructive' : 'success'}>
                      {c.status === 'paid' ? 'Fully applied' : c.status === 'voided' ? 'Voided' : 'Available'}
                    </Badge>
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    {c.outstanding > 0.005 && (
                      <Button size="sm" variant="outline" onClick={() => setAllocating(c)}>Apply</Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {allocating && (
        <AllocateDialog credit={allocating} direction={direction} onClose={() => setAllocating(null)} />
      )}
    </>
  )
}

function AllocateDialog({
  credit, direction, onClose,
}: { credit: Credit; direction: CreditDirection; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const docPath = direction === 'payable' ? 'bills' : 'invoices'
  const targetType = direction === 'payable' ? 'bill' : 'invoice'

  // The backend is the single source of truth for which documents this credit
  // can be applied to (same contact — by id OR name, same currency, open, owing).
  // We render exactly that list rather than re-deriving eligibility here.
  const { data: targets, isLoading } = useQuery<CreditTarget[]>({
    queryKey: ['credit-targets', credit.id],
    queryFn: () => api.get(`/credits/${credit.id}/targets`).then((r) => r.data),
  })
  const open = targets ?? []

  const [targetId, setTargetId] = useState<number | null>(null)
  const [amount, setAmount] = useState('')
  const target = open.find((d) => d.id === targetId) ?? null
  const maxAmount = target ? Math.min(credit.outstanding, target.outstanding) : credit.outstanding

  const pick = (d: CreditTarget) => {
    setTargetId(d.id)
    setAmount(Math.min(credit.outstanding, d.outstanding).toFixed(2))
  }

  const allocate = useMutation({
    mutationFn: () =>
      api.post(`/credits/${credit.id}/allocate`, {
        target_type: targetType, target_id: targetId, amount: parseFloat(amount),
      }),
    onSuccess: () => {
      toast(`Applied ${formatCurrency(parseFloat(amount), credit.currency)} of credit`)
      qc.invalidateQueries({ queryKey: ['credits'] })
      qc.invalidateQueries({ queryKey: ['credit-targets'] })
      qc.invalidateQueries({ queryKey: [docPath] })
      onClose()
    },
    onError: (e) => toast(e instanceof ApiError ? e.message : 'Could not apply credit', 'error'),
  })

  const amt = parseFloat(amount)
  const valid = targetId != null && amt > 0 && amt <= maxAmount + 0.005

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div className="w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
        <Card>
          <CardContent className="p-5 space-y-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="font-semibold">Allocate outstanding credit</h3>
                <p className="text-sm text-muted-foreground mt-0.5">
                  {KIND_LABEL[credit.kind]} · {credit.contact_name} ·{' '}
                  <span className="font-medium text-foreground">{formatCurrency(credit.outstanding, credit.currency)}</span>{' '}
                  available
                </p>
              </div>
              <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
                <X className="w-4 h-4" />
              </button>
            </div>

            {isLoading ? (
              <div className="flex justify-center py-8">
                <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
              </div>
            ) : !open.length ? (
              <p className="text-sm text-muted-foreground py-6 text-center">
                No open {targetType}s for {credit.contact_name} in {credit.currency} to apply this credit to.
              </p>
            ) : (
              <>
                <div className="space-y-1.5 max-h-60 overflow-y-auto">
                  {open.map((d) => (
                    <button
                      key={d.id}
                      onClick={() => pick(d)}
                      className={cn(
                        'w-full flex items-center justify-between rounded-md border px-3 py-2 text-left text-sm transition-colors',
                        targetId === d.id ? 'border-primary bg-primary/5' : 'hover:bg-muted/40',
                      )}
                    >
                      <span className="font-medium">{d.number ?? `${targetType} #${d.id}`}</span>
                      <span className="font-mono text-xs text-amber-700">
                        {formatCurrency(d.outstanding, d.currency)} owing
                      </span>
                    </button>
                  ))}
                </div>

                {target && (
                  <>
                    <div className="flex items-end gap-3">
                      <div className="flex-1">
                        <label className="text-xs text-muted-foreground">Amount to apply</label>
                        <Input value={amount} inputMode="decimal" onChange={(e) => setAmount(e.target.value)} />
                        <p className="text-[11px] text-muted-foreground mt-1">
                          Up to {formatCurrency(maxAmount, credit.currency)}
                        </p>
                      </div>
                      <Button onClick={() => allocate.mutate()} disabled={!valid || allocate.isPending}>
                        {allocate.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : 'Apply credit'}
                      </Button>
                    </div>
                    <div className="rounded-md bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                      After applying: {targetType} due{' '}
                      <span className="font-medium text-foreground">
                        {formatCurrency(Math.max(0, target.outstanding - (amt || 0)), credit.currency)}
                      </span>{' '}
                      · credit remaining{' '}
                      <span className="font-medium text-foreground">
                        {formatCurrency(Math.max(0, credit.outstanding - (amt || 0)), credit.currency)}
                      </span>
                    </div>
                  </>
                )}
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
