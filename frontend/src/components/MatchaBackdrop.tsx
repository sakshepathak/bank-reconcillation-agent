import { cn } from '@/lib/utils'

/**
 * A whisper-faint field of matcha doodles — leaves, steam curls, little cups,
 * sparkles — tiled behind the page content. Opacity is deliberately tiny so it
 * adds texture and personality without ever competing with the data. Purely
 * decorative and non-interactive.
 */
export default function MatchaBackdrop({ className }: { className?: string }) {
  return (
    <svg
      className={cn('pointer-events-none select-none w-full h-full', className)}
      aria-hidden="true"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <pattern id="matcha-doodle-field" width="150" height="150" patternUnits="userSpaceOnUse" patternTransform="rotate(-4)">
          <g
            fill="none"
            stroke="hsl(89 38% 30%)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            opacity="0.05"
          >
            {/* leaf */}
            <path d="M22 26c8 2 10 12 4.5 18-7.5-2-9.5-12-4.5-18Z" />
            <path d="M22 28v15" />
            {/* steam curls */}
            <path d="M104 20c-3.2 4 3.2 6 0 10.5" />
            <path d="M112 20c-3.2 4 3.2 6 0 10.5" />
            {/* tiny cup */}
            <path d="M80 96h17l-1.5 8.4a3 3 0 0 1-3 2.6h-8a3 3 0 0 1-3-2.6Z" />
            <path d="M97 99.5c2.8 0 2.8 5 0 5" />
            <path d="M77.5 109.5h22" />
            {/* sparkle */}
            <path d="M126 116l2 4.4 4.4 2-4.4 2-2 4.4-2-4.4-4.4-2 4.4-2Z" />
            {/* dots */}
            <circle cx="34" cy="104" r="1.7" fill="hsl(89 38% 30%)" stroke="none" />
            <circle cx="128" cy="64" r="1.7" fill="hsl(89 38% 30%)" stroke="none" />
            <circle cx="60" cy="40" r="1.7" fill="hsl(89 38% 30%)" stroke="none" />
          </g>
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#matcha-doodle-field)" />
    </svg>
  )
}
