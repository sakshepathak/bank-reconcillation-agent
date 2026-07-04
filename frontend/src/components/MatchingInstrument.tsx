import { useEffect, useState } from 'react'
import { Check, RotateCcw, ArrowRight } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * The Smart-Matching instrument — the dashboard's hero.
 *
 * Instead of a static "we match your bank lines" tile, this *shows the working*:
 * a messy bank line resolves into a known vendor, with a live confidence dial
 * and a reasoning trace that reveals why. It's a self-contained demonstration
 * (representative sample, not live data yet) so it looks alive even before the
 * first import. Fully theme-token driven — reads correctly in light and dark.
 */

const TRACE = [
  { k: 'amount',  v: '£420.00 → invoice INV‑2043 £420.00', verdict: 'exact' },
  { k: 'date',    v: '04 Jul · terms net‑30, due 12 Jul',   verdict: 'in window' },
  { k: 'vendor',  v: 'alias "POTCLAYS" → Potclays Limited',  verdict: 'learned' },
  { k: 'history', v: '6 prior payments · avg +3d late',      verdict: 'expected' },
]

const TARGET = 98
const R = 52
const CIRC = 2 * Math.PI * R

function usePrefersReducedMotion() {
  const [reduce, setReduce] = useState(
    () => typeof window !== 'undefined'
      && !!window.matchMedia
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )
  useEffect(() => {
    if (!window.matchMedia) return
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const on = () => setReduce(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return reduce
}

export default function MatchingInstrument() {
  const reduce = usePrefersReducedMotion()
  const [dial, setDial] = useState(reduce ? TARGET : 0)
  const [revealed, setRevealed] = useState(reduce ? TRACE.length : 0)
  const [runKey, setRunKey] = useState(0)

  useEffect(() => {
    if (reduce) { setDial(TARGET); setRevealed(TRACE.length); return }
    setDial(0)
    setRevealed(0)

    let raf = 0
    const dur = 1300
    let startT = 0
    const tick = (now: number) => {
      if (!startT) startT = now
      const p = Math.min((now - startT) / dur, 1)
      setDial(Math.round((1 - Math.pow(1 - p, 3)) * TARGET))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    const kickoff = window.setTimeout(() => { raf = requestAnimationFrame(tick) }, 400)
    const timers = TRACE.map((_, i) =>
      window.setTimeout(() => setRevealed((n) => Math.max(n, i + 1)), 650 + i * 260),
    )

    return () => {
      clearTimeout(kickoff)
      cancelAnimationFrame(raf)
      timers.forEach(clearTimeout)
    }
  }, [runKey, reduce])

  return (
    <div className="relative overflow-hidden h-full rounded-2xl border bg-card shadow-sm p-6 flex flex-col">
      {/* faint jade wash, top-right — pure token so it re-tints per theme */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{ background: 'radial-gradient(120% 90% at 82% 0%, hsl(var(--primary) / 0.08), transparent 60%)' }}
      />

      {/* header */}
      <div className="relative flex items-center justify-between">
        <p className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          <span className="relative flex h-2 w-2">
            {!reduce && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary/60" />}
            <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
          </span>
          Smart matching · live
        </p>
        <button
          type="button"
          onClick={() => setRunKey((k) => k + 1)}
          className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium text-muted-foreground hover:text-primary hover:bg-muted transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <RotateCcw className="w-3.5 h-3.5" /> Replay
        </button>
      </div>

      {/* the raw, messy bank line */}
      <div className="relative mt-4 flex items-center gap-2 flex-wrap rounded-lg border border-dashed bg-muted/40 px-3 py-2.5 font-mono text-[13px]">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground">bank line</span>
        <span className="text-primary font-semibold">SQ&nbsp;*POTCLAYS</span>
        <span className="text-foreground">STOKE</span>
        <span className="text-primary font-semibold">GB</span>
        <span className="text-foreground">CARD</span>
        <span className="text-primary font-semibold">4471</span>
        <span className="ml-auto text-foreground">−£420.00</span>
      </div>

      {/* resolved vendor + confidence dial */}
      <div className="relative mt-5 flex items-center gap-5">
        <div className="flex-1 min-w-0">
          <p className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">
            whisks into <ArrowRight className="w-3.5 h-3.5 text-primary" />
          </p>
          <p className="font-display text-[26px] font-semibold text-foreground mt-1 leading-tight truncate">
            Potclays Limited
          </p>
          <div className="flex gap-1.5 mt-2 flex-wrap">
            <span className="text-[11px] font-medium px-2 py-0.5 rounded-full border border-primary/30 text-primary bg-primary/5">supplier</span>
            <span className="text-[11px] font-medium px-2 py-0.5 rounded-full border text-muted-foreground font-mono">INV‑2043</span>
            <span className="text-[11px] font-medium px-2 py-0.5 rounded-full border text-muted-foreground">net‑30</span>
          </div>
        </div>

        <div className="relative w-[116px] h-[116px] grid place-items-center flex-shrink-0">
          <svg className="absolute inset-0 -rotate-90" viewBox="0 0 116 116" aria-hidden="true">
            <circle cx="58" cy="58" r={R} fill="none" strokeWidth={8} style={{ stroke: 'hsl(var(--muted))' }} />
            <circle
              cx="58" cy="58" r={R} fill="none" strokeWidth={8} strokeLinecap="round"
              strokeDasharray={CIRC}
              style={{
                stroke: 'hsl(var(--primary))',
                strokeDashoffset: CIRC * (1 - dial / 100),
                transition: reduce ? 'none' : 'stroke-dashoffset 0.9s cubic-bezier(.2,.8,.2,1)',
                filter: 'drop-shadow(0 0 5px hsl(var(--primary) / 0.4))',
              }}
            />
          </svg>
          <div className="text-center">
            <div className="font-display text-3xl font-semibold text-foreground tabular-nums leading-none">
              {dial}<span className="text-base text-primary">%</span>
            </div>
            <div className="text-[9px] uppercase tracking-wider text-muted-foreground mt-1">confidence</div>
          </div>
        </div>
      </div>

      {/* the working — the reasoning trace */}
      <div className="relative mt-5 border-t pt-4 flex-1">
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2.5">
          the working — why this match
        </p>
        <ul className="space-y-1.5">
          {TRACE.map((t, i) => (
            <li
              key={t.k}
              className={cn(
                'grid grid-cols-[62px_1fr_auto] items-baseline gap-3 font-mono text-[12px] transition-all duration-300',
                i < revealed ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-1',
              )}
            >
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{t.k}</span>
              <span className="text-muted-foreground truncate">{t.v}</span>
              <span className="inline-flex items-center gap-1 text-primary text-[11px] whitespace-nowrap">
                <Check className="w-3 h-3" /> {t.verdict}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <p className="relative mt-4 text-[11px] text-muted-foreground">
        Every match is explainable — you can see exactly why.
      </p>
    </div>
  )
}
