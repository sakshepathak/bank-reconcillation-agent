import type { ReactNode, ElementType } from 'react'
import { cn } from '@/lib/utils'

export interface Stat {
  label: string
  value: ReactNode
  sub?: ReactNode
  icon?: ElementType
  /** Emphasise (e.g. amber) — for the "needs attention" metric. */
  accent?: boolean
}

/**
 * One bordered bar of metrics with divided cells — the professional
 * alternative to a row of separate KPI cards (which read as "children's book").
 * Every metric value renders at the SAME size for a consistent figure scale.
 *
 *   <StatStrip stats={[{ label: 'To reconcile', value: 12, accent: true }, …]} />
 */
export function StatStrip({ stats, className }: { stats: Stat[]; className?: string }) {
  return (
    <div className={cn('flex flex-wrap rounded-lg border border-border bg-card divide-x divide-border', className)}>
      {stats.map((s, i) => (
        <div key={i} className="flex-1 min-w-[160px] px-4 py-3">
          <div className="flex items-center gap-1.5">
            {s.icon && <s.icon className={cn('w-3.5 h-3.5 flex-shrink-0', s.accent ? 'text-amber-600' : 'text-muted-foreground')} />}
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground truncate">{s.label}</p>
          </div>
          <p className={cn('text-lg font-semibold font-mono mt-1 truncate', s.accent ? 'text-amber-700' : 'text-foreground')}>
            {s.value}
          </p>
          {s.sub && <p className="text-xs text-muted-foreground mt-0.5 truncate">{s.sub}</p>}
        </div>
      ))}
    </div>
  )
}
