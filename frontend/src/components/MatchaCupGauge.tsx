import { useId } from 'react'
import { cn } from '@/lib/utils'

/**
 * A matcha cup that fills up to a percentage — a playful gauge for things like
 * the overall match rate. The green liquid is clipped to the cup interior and
 * its height is driven by `value` (0–100), with a pale foam line on top and a
 * smiling face so it reads as Matcha, not just a meter.
 */
export default function MatchaCupGauge({
  value,
  className,
}: {
  value: number
  className?: string
}) {
  const id = useId().replace(/:/g, '')
  const pct = Math.max(0, Math.min(100, value))

  // Interior spans y ≈ 14.5 (rim) → 28.6 (base). Fill rises from the base.
  const top = 14.5
  const bottom = 28.6
  const fillY = bottom - (bottom - top) * (pct / 100)
  const interior = 'M9 14.5H27V24a4.6 4.6 0 0 1-4.6 4.6H13.6A4.6 4.6 0 0 1 9 24Z'

  return (
    <svg viewBox="0 0 36 34" className={cn('w-16 h-16', className)} aria-hidden="true">
      <defs>
        <clipPath id={`cup-${id}`}>
          <path d={interior} />
        </clipPath>
      </defs>

      {/* the matcha, clipped to the cup */}
      <g clipPath={`url(#cup-${id})`}>
        <rect x="8" y={fillY} width="20" height={bottom - fillY + 0.5} fill="#8fb850" />
        {/* pale foam line riding the surface */}
        {pct > 4 && pct < 99 && (
          <rect x="8" y={fillY} width="20" height="1.4" fill="#eef4dc" opacity="0.9" />
        )}
      </g>

      {/* a happy little face on the cup */}
      <g>
        <circle cx="14.7" cy="21.8" r="1.35" fill="#23310f" className="animate-blink" />
        <circle cx="21.3" cy="21.8" r="1.35" fill="#23310f" className="animate-blink" />
        <path d="M15 24.4q3 2.3 6 0" stroke="#23310f" strokeWidth="1.3" strokeLinecap="round" fill="none" />
      </g>

      {/* cup walls + rim + handle */}
      <path d={interior} stroke="#33431f" strokeWidth="1.8" strokeLinejoin="round" fill="none" />
      <path d="M7.5 14.5H28.5" stroke="#33431f" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M27 16.4c4.2 0 4.2 7.4 0 7.4" stroke="#33431f" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}
