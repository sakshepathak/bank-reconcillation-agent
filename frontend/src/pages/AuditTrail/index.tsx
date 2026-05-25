import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, ChevronLeft, ChevronRight } from 'lucide-react'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn, formatDate } from '@/lib/utils'
import type { Match } from '@/types'

const PAGE_SIZE = 50

const STATUS_VARIANT: Record<string, 'success' | 'warning' | 'destructive' | 'info' | 'muted'> = {
  exact: 'success',
  fuzzy: 'warning',
  one_to_many: 'info',
  many_to_one: 'info',
  human_corrected: 'success',
  unmatched: 'destructive',
  possible: 'warning',
}

export default function AuditTrail() {
  const [page, setPage] = useState(0)

  const { data: records, isLoading } = useQuery<Match[]>({
    queryKey: ['audit', page],
    queryFn: () =>
      api.get('/audit/', { params: { skip: page * PAGE_SIZE, limit: PAGE_SIZE } }).then((r) => r.data),
  })

  const hasNext = (records?.length ?? 0) === PAGE_SIZE
  const hasPrev = page > 0

  const handleExport = () => {
    window.open('/api/v1/audit/export', '_blank')
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold">Audit Trail</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Immutable record of every reconciliation decision.
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={handleExport}>
          <Download className="w-3.5 h-3.5 mr-1.5" />
          Export CSV
        </Button>
      </div>

      {/* Table */}
      <Card>
        <CardContent className="p-0 overflow-x-auto">
          {isLoading ? (
            <div className="p-4 space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : !records?.length ? (
            <div className="py-12 text-center text-sm text-muted-foreground">
              No audit records yet. Run a reconciliation to generate entries.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/40">
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground whitespace-nowrap">
                    Run ID
                  </th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground whitespace-nowrap">
                    Bank TxN
                  </th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground whitespace-nowrap">
                    Ledger TxN
                  </th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">
                    Status
                  </th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold text-muted-foreground">
                    Score
                  </th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold text-muted-foreground whitespace-nowrap">
                    Amt Δ
                  </th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold text-muted-foreground whitespace-nowrap">
                    Date Δ
                  </th>
                  <th className="px-4 py-2.5 text-center text-xs font-semibold text-muted-foreground">
                    Approved
                  </th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold text-muted-foreground">
                    Date
                  </th>
                </tr>
              </thead>
              <tbody>
                {records.map((r, i) => (
                  <tr
                    key={r.id}
                    className={cn(
                      'border-b last:border-0 transition-colors hover:bg-muted/30',
                      i % 2 === 0 ? '' : 'bg-muted/10',
                    )}
                  >
                    <td className="px-4 py-2.5">
                      <span className="font-mono text-xs text-muted-foreground truncate block max-w-[120px]">
                        {r.run_id}
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className="font-mono text-xs truncate block max-w-[120px]">
                        {r.bank_txn_id}
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className="font-mono text-xs text-muted-foreground truncate block max-w-[120px]">
                        {r.ledger_txn_id ?? '—'}
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge variant={STATUS_VARIANT[r.status] ?? 'muted'}>
                        {r.status.replace(/_/g, ' ')}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs">
                      {(r.score * 100).toFixed(0)}%
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs">
                      {r.amount_diff !== null ? (
                        <span
                          className={cn(
                            Math.abs(r.amount_diff) > 0.01 ? 'text-amber-600' : 'text-emerald-600',
                          )}
                        >
                          {r.amount_diff >= 0 ? '+' : ''}
                          {r.amount_diff.toFixed(2)}
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs">
                      {r.date_diff_days !== null && r.date_diff_days !== 0 ? (
                        <span className="text-amber-600">{r.date_diff_days}d</span>
                      ) : r.date_diff_days === 0 ? (
                        <span className="text-emerald-600">0d</span>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      {r.human_approved === true ? (
                        <Badge variant="success">Yes</Badge>
                      ) : r.human_approved === false ? (
                        <Badge variant="destructive">No</Badge>
                      ) : r.requires_human_review ? (
                        <Badge variant="warning">Pending</Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">Auto</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-right text-xs text-muted-foreground whitespace-nowrap">
                      {formatDate(r.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {/* Pagination */}
      {(hasPrev || hasNext) && (
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            Page {page + 1} · {records?.length ?? 0} records
          </span>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => setPage((p) => p - 1)}
              disabled={!hasPrev}
            >
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setPage((p) => p + 1)}
              disabled={!hasNext}
            >
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
