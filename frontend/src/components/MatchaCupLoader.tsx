import { cn } from '@/lib/utils'

/**
 * The "thinking" indicator — a matcha cup whose green liquid fills up and drains
 * on a loop (the liquid rect is clipped to the cup interior and animated by the
 * `.matcha-liquid` keyframe in index.css). Used wherever Matcha is working.
 */
export default function MatchaCupLoader({ className }: { className?: string }) {
  const interior = 'M9 14.5H27V24a4.6 4.6 0 0 1-4.6 4.6H13.6A4.6 4.6 0 0 1 9 24Z'
  return (
    <svg viewBox="0 0 36 34" fill="none" className={cn('w-8 h-8', className)} aria-hidden="true">
      <defs>
        <clipPath id="matcha-cup-interior">
          <path d={interior} />
        </clipPath>
      </defs>
      {/* the matcha, clipped to the cup, fills + empties */}
      <g clipPath="url(#matcha-cup-interior)">
        <rect className="matcha-liquid" x="8" y="13" width="20" height="17" fill="#8fb850" />
      </g>
      {/* cup walls + rim + handle */}
      <path d={interior} stroke="#33431f" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M7.5 14.5H28.5" stroke="#33431f" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M27 16.4c4.2 0 4.2 7.4 0 7.4" stroke="#33431f" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}
