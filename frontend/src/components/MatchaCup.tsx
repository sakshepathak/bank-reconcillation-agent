import { cn } from '@/lib/utils'

/**
 * Matcha the bot — a little green matcha mug with a face. Green body (the
 * matcha), a creamy foam rim, a handle, and a blinking, smiling face so it reads
 * as a friendly assistant rather than just an icon. Colours are baked in so it
 * looks right on the green bubble or on a light card. Steam is drawn by the
 * caller (it animates separately).
 */
export default function MatchaCup({
  className,
  face = true,
  blink = true,
}: {
  className?: string
  face?: boolean
  blink?: boolean
}) {
  return (
    <svg viewBox="0 0 36 36" fill="none" className={cn('w-8 h-8', className)} aria-hidden="true">
      {/* saucer */}
      <path d="M9 31.6h18" stroke="#33431f" strokeWidth="1.7" strokeLinecap="round" />
      {/* handle */}
      <path d="M27.5 17c4.4 0 4.4 8 0 8" stroke="#33431f" strokeWidth="1.8" strokeLinecap="round" />
      {/* mug body — the matcha */}
      <rect x="8.5" y="11.5" width="19" height="18" rx="5.2" fill="#7d9e37" stroke="#33431f" strokeWidth="1.8" />
      {/* creamy foam rim */}
      <path
        d="M10.5 16.4V13.6a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2v2.8Z"
        fill="#eef4dc"
        stroke="#33431f"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />

      {face && (
        <g>
          {/* cheeks */}
          <circle cx="12.8" cy="24.2" r="1.7" fill="#f1a3ad" opacity="0.7" />
          <circle cx="23.2" cy="24.2" r="1.7" fill="#f1a3ad" opacity="0.7" />
          {/* eyes (blink) */}
          <g className={blink ? 'animate-blink' : undefined}>
            <circle cx="14.6" cy="21.4" r="1.6" fill="#23310f" />
            <circle cx="21.4" cy="21.4" r="1.6" fill="#23310f" />
            <circle cx="15.1" cy="20.9" r="0.45" fill="#fff" />
            <circle cx="21.9" cy="20.9" r="0.45" fill="#fff" />
          </g>
          {/* smile */}
          <path d="M15 24.2q3 2.6 6 0" stroke="#23310f" strokeWidth="1.4" strokeLinecap="round" fill="none" />
        </g>
      )}
    </svg>
  )
}
