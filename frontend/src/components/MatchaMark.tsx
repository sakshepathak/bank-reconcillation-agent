import { cn } from '@/lib/utils'

/**
 * The Matcha brand mark — a hand-drawn money-bill doodle with a matcha leaf
 * medallion and a little wisp of steam (money + matcha, the whole pun in one
 * glyph). Stroke is `currentColor`, so it inherits white on the green sidebar
 * and matcha-green on light surfaces. Decorative only — always paired with a
 * text label for meaning.
 */
export default function MatchaMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 48 48"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn('w-6 h-6', className)}
      aria-hidden="true"
    >
      {/* steam wisps rising off the note (the tea reference) */}
      <path d="M19.5 11.5c-1.1-1.6 1-2.5 0-4.3" opacity="0.6" />
      <path d="M28.5 11.5c-1.1-1.6 1-2.5 0-4.3" opacity="0.6" />
      {/* the banknote */}
      <rect x="5" y="15" width="38" height="23" rx="4.5" />
      {/* inner dashed frame, the way a bill is engraved */}
      <rect x="9" y="19" width="30" height="15" rx="2.5" strokeDasharray="2 3" opacity="0.5" />
      {/* matcha-leaf medallion in the centre */}
      <path d="M24 22.4C27 25 27 28 24 30.2 21 28 21 25 24 22.4Z" />
      <path d="M24 23.4v6" />
    </svg>
  )
}
