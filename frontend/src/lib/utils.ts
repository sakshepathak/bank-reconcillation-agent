import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatCurrency(amount: number, currency = 'GBP'): string {
  return new Intl.NumberFormat('en-GB', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
  }).format(amount)
}

export function formatDate(iso: string): string {
  if (!iso) return '—'
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

export function formatPct(value: number): string {
  return `${value.toFixed(1)}%`
}

/**
 * A document is PARTIALLY PAID when some — but not all — of it has been settled
 * (paid_amount > 0 and still owing). This is derived from amounts, NOT a status
 * value, so a partial keeps status 'awaiting_payment' yet shows in BOTH the
 * Awaiting Payment and Paid tabs. One shared definition for Purchases + Sales.
 */
export function isPartiallyPaid(d: { status?: string; paid_amount?: number; outstanding?: number }): boolean {
  return d.status !== 'voided' && (d.paid_amount ?? 0) > 0.005 && (d.outstanding ?? 0) > 0.005
}
