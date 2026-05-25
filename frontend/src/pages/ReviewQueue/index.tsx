import { useCallback, useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, CheckSquare, Keyboard, X } from 'lucide-react'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn, formatDate } from '@/lib/utils'
import type { Match } from '@/types'

type ConfidenceFilter = 'all' | 'high' | 'medium' | 'low'

const STATUS_VARIANT: Record<string, 'success' | 'warning' | 'destructive' | 'info' | 'muted'> = {
  exact: 'success',
  fuzzy: 'warning',
  one_to_many: 'info',
  many_to_one: 'info',
  human_corrected: 'success',
  unmatched: 'destructive',
  possible: 'warning',
}

function confidenceVariant(score: number): 'success' | 'warning' | 'destructive' {
  if (score >= 0.9) return 'success'
  if (score >= 0.7) return 'warning'
  return 'destructive'
}

function Toast({ message, onClose }: { message: string; onClose: () => void }) {
  useEffect(() => {
    const t = setTimeout(onClose, 4000)
    return () => clearTimeout(t)
  }, [onClose])

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-foreground text-background text-sm px-4 py-2.5 rounded-lg shadow-xl flex items-center gap-3">
      {message}
      <button onClick={onClose} className="text-background/60 hover:text-background">
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  )
}

export default function ReviewQueue() {
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [lastIdx, setLastIdx] = useState<number | null>(null)
  const [filter, setFilter] = useState<ConfidenceFilter>('all')
  const [toast, setToast] = useState<string | null>(null)

  const { data: pending, isLoading } = useQuery<Match[]>({
    queryKey: ['matches', 'pending'],
    queryFn: () => api.get('/matches/pending').then((r) => r.data),
  })

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: ['matches', 'pending'] }),
    [queryClient],
  )

  type OptCtx = { prev?: Match[] }

  const approveMutation = useMutation<unknown, Error, number, OptCtx>({
    mutationFn: (id) => api.patch(`/matches/${id}/approve`),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: ['matches', 'pending'] })
      const prev = queryClient.getQueryData<Match[]>(['matches', 'pending'])
      queryClient.setQueryData<Match[]>(['matches', 'pending'], (old) => old?.filter((m) => m.id !== id) ?? [])
      return { prev }
    },
    onError: (_e, _id, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(['matches', 'pending'], ctx.prev)
    },
    onSettled: invalidate,
  })

  const rejectMutation = useMutation<unknown, Error, number, OptCtx>({
    mutationFn: (id) => api.patch(`/matches/${id}/reject`),
    onMutate: async (id) => {
      await queryClient.cancelQueries({ queryKey: ['matches', 'pending'] })
      const prev = queryClient.getQueryData<Match[]>(['matches', 'pending'])
      queryClient.setQueryData<Match[]>(['matches', 'pending'], (old) => old?.filter((m) => m.id !== id) ?? [])
      return { prev }
    },
    onError: (_e, _id, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(['matches', 'pending'], ctx.prev)
    },
    onSettled: invalidate,
  })

  const bulkApproveMutation = useMutation({
    mutationFn: (ids: number[]) => api.post('/matches/bulk-approve', { ids }),
    onSuccess: (_data, ids) => {
      setSelected(new Set())
      setToast(`Approved ${ids.length} match${ids.length === 1 ? '' : 'es'}`)
      invalidate()
    },
  })

  const bulkRejectMutation = useMutation({
    mutationFn: (ids: number[]) => api.post('/matches/bulk-reject', { ids }),
    onSuccess: (_data, ids) => {
      setSelected(new Set())
      setToast(`Rejected ${ids.length} match${ids.length === 1 ? '' : 'es'}`)
      invalidate()
    },
  })

  const filtered = (pending ?? []).filter((m) => {
    if (filter === 'high') return m.score >= 0.9
    if (filter === 'medium') return m.score >= 0.7 && m.score < 0.9
    if (filter === 'low') return m.score < 0.7
    return true
  })

  const highConfIds = (pending ?? []).filter((m) => m.score >= 0.9).map((m) => m.id)
  const selectedArr = [...selected]
  const allSelected = filtered.length > 0 && filtered.every((m) => selected.has(m.id))
  const someSelected = filtered.some((m) => selected.has(m.id))

  const toggleSelect = (id: number, idx: number, shiftHeld: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (shiftHeld && lastIdx !== null) {
        const lo = Math.min(lastIdx, idx)
        const hi = Math.max(lastIdx, idx)
        filtered.slice(lo, hi + 1).forEach((m) => next.add(m.id))
      } else {
        if (next.has(id)) next.delete(id)
        else next.add(id)
      }
      return next
    })
    setLastIdx(idx)
  }

  const toggleAll = () => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (allSelected) filtered.forEach((m) => next.delete(m.id))
      else filtered.forEach((m) => next.add(m.id))
      return next
    })
  }

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.key === 'a' && selectedArr.length > 0) bulkApproveMutation.mutate(selectedArr)
      if (e.key === 'r' && selectedArr.length > 0) bulkRejectMutation.mutate(selectedArr)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [selectedArr, bulkApproveMutation, bulkRejectMutation])

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold">Review Queue</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Matches flagged for human review before reconciliation is finalised.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {pending && (
            <Badge variant={pending.length > 0 ? 'warning' : 'success'}>
              {pending.length} pending
            </Badge>
          )}
          {highConfIds.length > 0 && (
            <Button
              size="sm"
              onClick={() => bulkApproveMutation.mutate(highConfIds)}
              disabled={bulkApproveMutation.isPending}
            >
              <Check className="w-3.5 h-3.5 mr-1.5" />
              Approve all ≥90% ({highConfIds.length})
            </Button>
          )}
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center bg-muted rounded-md p-0.5 gap-0.5">
          {(['all', 'high', 'medium', 'low'] as ConfidenceFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                'px-3 py-1 text-xs font-medium rounded transition-colors',
                filter === f
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {f === 'all' ? 'All' : f === 'high' ? '≥90%' : f === 'medium' ? '70–89%' : '<70%'}
            </button>
          ))}
        </div>

        {someSelected && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">{selectedArr.length} selected</span>
            <Button
              size="sm"
              className="h-7 text-xs"
              onClick={() => bulkApproveMutation.mutate(selectedArr)}
              disabled={bulkApproveMutation.isPending}
            >
              Approve ({selectedArr.length})
            </Button>
            <Button
              size="sm"
              variant="destructive"
              className="h-7 text-xs"
              onClick={() => bulkRejectMutation.mutate(selectedArr)}
              disabled={bulkRejectMutation.isPending}
            >
              Reject ({selectedArr.length})
            </Button>
          </div>
        )}

        <div className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
          <Keyboard className="w-3 h-3" />
          <span>A = approve · R = reject</span>
        </div>
      </div>

      {/* List */}
      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : !filtered.length ? (
        <Card>
          <CardContent className="py-10 text-center">
            <CheckSquare className="w-8 h-8 text-emerald-500 mx-auto mb-2 opacity-60" />
            <p className="text-sm text-muted-foreground">
              {filter === 'all'
                ? 'All caught up — no items need review.'
                : `No ${filter} confidence items pending.`}
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-1.5">
          <div className="flex items-center gap-3 px-4 py-1">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={toggleAll}
              className="w-4 h-4 accent-primary cursor-pointer"
            />
            <span className="text-xs text-muted-foreground">Select all ({filtered.length})</span>
          </div>

          {filtered.map((m, idx) => {
            const isSelected = selected.has(m.id)
            return (
              <Card
                key={m.id}
                className={cn(
                  'transition-colors cursor-pointer',
                  isSelected && 'ring-2 ring-primary/40 bg-primary/5',
                )}
                onClick={(e) => toggleSelect(m.id, idx, e.shiftKey)}
              >
                <CardContent className="py-3 px-4">
                  <div className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSelect(m.id, idx, false)}
                      onClick={(e) => e.stopPropagation()}
                      className="w-4 h-4 accent-primary cursor-pointer flex-shrink-0"
                    />

                    {/* Confidence badge */}
                    <Badge
                      variant={confidenceVariant(m.score)}
                      className="w-12 justify-center flex-shrink-0 font-mono"
                    >
                      {(m.score * 100).toFixed(0)}%
                    </Badge>

                    {/* Details */}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge variant={STATUS_VARIANT[m.status] ?? 'muted'}>
                          {m.status.replace(/_/g, ' ')}
                        </Badge>
                        <span className="font-mono text-xs text-muted-foreground truncate">
                          {m.bank_txn_id}
                        </span>
                        {m.ledger_txn_id && (
                          <span className="text-xs text-muted-foreground">→ {m.ledger_txn_id}</span>
                        )}
                      </div>

                      {m.reasoning_path && (
                        <p className="text-xs text-muted-foreground mt-1 line-clamp-2 italic">
                          {m.reasoning_path}
                        </p>
                      )}

                      <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
                        <span>{formatDate(m.created_at)}</span>
                        {m.amount_diff !== null && (
                          <span
                            className={cn(
                              'font-mono',
                              Math.abs(m.amount_diff) > 0.01
                                ? 'text-amber-600'
                                : 'text-emerald-600',
                            )}
                          >
                            Δ{m.amount_diff >= 0 ? '+' : ''}
                            {m.amount_diff.toFixed(2)}
                          </span>
                        )}
                        {m.date_diff_days !== null && m.date_diff_days !== 0 && (
                          <span className="text-amber-600">{m.date_diff_days}d apart</span>
                        )}
                      </div>
                    </div>

                    {/* Actions */}
                    <div
                      className="flex items-center gap-2 flex-shrink-0"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 px-2.5 text-xs text-emerald-700 border-emerald-200 hover:bg-emerald-50"
                        onClick={() => approveMutation.mutate(m.id)}
                        disabled={approveMutation.isPending}
                      >
                        <Check className="w-3 h-3 mr-1" />
                        Approve
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 px-2.5 text-xs text-rose-600 border-rose-200 hover:bg-rose-50"
                        onClick={() => rejectMutation.mutate(m.id)}
                        disabled={rejectMutation.isPending}
                      >
                        <X className="w-3 h-3 mr-1" />
                        Reject
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      {toast && <Toast message={toast} onClose={() => setToast(null)} />}
    </div>
  )
}
