import { cn } from '@/lib/utils'

/**
 * Hand-drawn matcha doodles — leaves, a bamboo whisk, sparkles, coins, squiggles,
 * beans, steam. All stroke = `currentColor`, so a parent sets colour + opacity
 * (e.g. `text-primary/[0.08]`) and they tint correctly in light and dark. Purely
 * decorative; every one is pointer-events-none + aria-hidden.
 */

type P = { className?: string }
const stroke = {
  fill: 'none' as const,
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}
const base = 'pointer-events-none select-none'

export function Leaf({ className }: P) {
  return (
    <svg viewBox="0 0 24 24" {...stroke} className={cn(base, className)} aria-hidden="true">
      <path d="M12 3c5.5 3 5.5 13 0 18-5.5-5-5.5-15 0-18Z" />
      <path d="M12 6.5v10.5" />
      <path d="M12 10.5 8.9 8.6M12 13.4l3.1-1.9" />
    </svg>
  )
}

/** A chasen — the bamboo matcha whisk. */
export function Whisk({ className }: P) {
  return (
    <svg viewBox="0 0 24 24" {...stroke} className={cn(base, className)} aria-hidden="true">
      <path d="M12 2.5V9" />
      <path d="M12 9c-3.4 2.2-4.6 5.6-4.8 12M12 9c-1.4 2.4-1.8 6-1.7 12M12 9c1.4 2.4 1.8 6 1.7 12M12 9c3.4 2.2 4.6 5.6 4.8 12" />
      <path d="M9.4 15.5h5.2" />
    </svg>
  )
}

export function Sparkle({ className }: P) {
  return (
    <svg viewBox="0 0 24 24" {...stroke} className={cn(base, className)} aria-hidden="true">
      <path d="M12 3c.7 4.6 2 5.9 6.6 6.6C14 10.3 12.7 11.6 12 16.2c-.7-4.6-2-5.9-6.6-6.6C10 8.9 11.3 7.6 12 3Z" />
    </svg>
  )
}

export function Coin({ className }: P) {
  return (
    <svg viewBox="0 0 24 24" {...stroke} className={cn(base, className)} aria-hidden="true">
      <circle cx="12" cy="12" r="8.4" />
      <path d="M14.1 8.9c-1.7-1.3-4.1-.6-4.1 1.6 0 2.7 2.9 2.5 2.9 4.7 0 1.4-1.5 2.1-3.1 1.2" />
      <path d="M9 12.4h4.5" />
    </svg>
  )
}

export function Squiggle({ className }: P) {
  return (
    <svg viewBox="0 0 28 12" {...stroke} className={cn(base, className)} aria-hidden="true">
      <path d="M2 8c3-5 6 5 9 0s6-5 9 0 5 3 6 1" />
    </svg>
  )
}

/** A little matcha bean / blob. */
export function Bean({ className }: P) {
  return (
    <svg viewBox="0 0 24 24" {...stroke} className={cn(base, className)} aria-hidden="true">
      <path d="M7.5 4.4c5.3-2.1 12 1.7 12 8.6 0 6.4-6.6 8.4-11 6.3S1.4 6.6 7.5 4.4Z" />
      <path d="M9 6.5c-2.2 3.5-2 8 .5 11.5" opacity="0.6" />
    </svg>
  )
}

export function SteamCurl({ className }: P) {
  return (
    <svg viewBox="0 0 24 24" {...stroke} className={cn(base, className)} aria-hidden="true">
      <path d="M9 3.5c-2.6 3.6 2.6 4.7 0 8.3M15 3.5c-2.6 3.6 2.6 4.7 0 8.3" />
    </svg>
  )
}

/** A dotted arc — good as a "flow" connector between two things. */
export function DottedArc({ className }: P) {
  return (
    <svg viewBox="0 0 40 20" fill="none" stroke="currentColor" strokeWidth={1.8}
      strokeLinecap="round" strokeDasharray="0.5 5" className={cn(base, className)} aria-hidden="true">
      <path d="M2 17C10 3 30 3 38 17" />
    </svg>
  )
}

/**
 * A fixed, tasteful scatter of doodles for a page background. Absolutely
 * positioned inside a `relative` parent; sits behind content, very low opacity.
 */
export function ScatterDoodles({ className }: P) {
  return (
    <div className={cn('pointer-events-none absolute inset-0 overflow-hidden text-primary', className)} aria-hidden="true">
      <Leaf className="absolute right-[5%] top-[1%] w-9 h-9 opacity-[0.08] -rotate-12 animate-sway" />
      <Sparkle className="absolute left-[2%] top-[26%] w-6 h-6 opacity-[0.09]" />
      <Squiggle className="absolute right-[16%] top-[40%] w-14 opacity-[0.07]" />
      <Coin className="absolute left-[6%] bottom-[14%] w-7 h-7 opacity-[0.07]" />
      <Whisk className="absolute right-[3%] bottom-[10%] w-10 h-10 opacity-[0.07] rotate-6 animate-sway" />
      <Bean className="absolute left-[46%] top-[2%] w-6 h-6 opacity-[0.06] rotate-12" />
      <Sparkle className="absolute right-[38%] bottom-[4%] w-5 h-5 opacity-[0.08]" />
    </div>
  )
}
