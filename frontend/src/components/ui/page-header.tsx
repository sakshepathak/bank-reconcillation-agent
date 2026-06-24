import type { ReactNode, ElementType } from 'react'
import { cn } from '@/lib/utils'

/**
 * The one page header used across the app — guarantees a consistent title size
 * and spacing everywhere. Optional leading icon and right-aligned actions.
 *
 *   <PageHeader title="Sales" subtitle="Invoices you've issued" actions={<Button/>} />
 */
export function PageHeader({
  title, subtitle, icon: Icon, actions, className,
}: {
  title: string
  subtitle?: string
  icon?: ElementType
  actions?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex items-start justify-between gap-4', className)}>
      <div className="flex items-center gap-3 min-w-0">
        {Icon && (
          <div className="w-10 h-10 rounded-lg bg-primary-subtle text-primary flex items-center justify-center flex-shrink-0">
            <Icon className="w-5 h-5" />
          </div>
        )}
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight text-foreground truncate">{title}</h1>
          {subtitle && <p className="text-sm text-muted-foreground mt-0.5">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2 flex-shrink-0">{actions}</div>}
    </div>
  )
}
