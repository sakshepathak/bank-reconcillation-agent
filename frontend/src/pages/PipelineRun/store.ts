/**
 * Pipeline Run state — lives in a module-level zustand store, NOT React state,
 * so the run results, progress and selection SURVIVE navigating away and back.
 * The component just renders this; only `Clear` (or starting a new run) resets it.
 *
 * The run loop also lives here, so it keeps streaming results into the store even
 * if the user leaves the page mid-run — when they return, it's up to date.
 */
import { create } from 'zustand'
import { api } from '@/lib/api'
import type { PipelineEntry, Notice } from './types'

const CONCURRENCY = 4

export type SortDir = 'asc' | 'desc'

interface PipelineState {
  entries: PipelineEntry[]
  progress: { done: number; total: number }
  running: boolean
  runId: number
  accountId: number | null
  expanded: Set<number>
  allExpanded: boolean
  notice: Notice | null
  sortDir: SortDir // results ordering by statement date: 'asc' = oldest first

  setAccountId: (id: number | null) => void
  setNotice: (n: Notice | null) => void
  setAllExpanded: (v: boolean) => void
  toggleRow: (id: number) => void
  toggleSort: () => void
  clear: () => void
  run: (acctOverride?: number | null) => Promise<void>
}

export const usePipelineStore = create<PipelineState>((set, get) => ({
  entries: [],
  progress: { done: 0, total: 0 },
  running: false,
  runId: 0,
  accountId: null,
  expanded: new Set<number>(),
  allExpanded: false,
  notice: null,
  sortDir: 'asc',

  setAccountId: (accountId) => set({ accountId }),
  setNotice: (notice) => set({ notice }),
  setAllExpanded: (allExpanded) => set({ allExpanded }),
  toggleSort: () => set((s) => ({ sortDir: s.sortDir === 'asc' ? 'desc' : 'asc' })),

  toggleRow: (id) =>
    set((s) => {
      const next = new Set(s.expanded)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return { expanded: next }
    }),

  // Reset the displayed run (cancels any in-flight run via the runId bump).
  // Keeps the selected account — only the results/progress/UI are cleared.
  clear: () =>
    set((s) => ({
      entries: [],
      progress: { done: 0, total: 0 },
      running: false,
      runId: s.runId + 1,
      expanded: new Set<number>(),
      allExpanded: false,
      notice: null,
    })),

  // Run the cascade over every line, streaming results in with bounded
  // concurrency so the demo is live but not painfully slow on a long statement.
  run: async (acctOverride) => {
    const acct = acctOverride !== undefined ? acctOverride : get().accountId
    const runId = get().runId + 1
    set({
      runId,
      expanded: new Set<number>(),
      allExpanded: false,
      entries: [],
      progress: { done: 0, total: 0 },
      notice: null,
      running: true,
    })

    try {
      const lines: { id: number }[] = await api
        .get('/statement-lines/pipeline-lines', { params: acct != null ? { bank_account_id: acct } : {} })
        .then((r) => r.data)

      if (get().runId !== runId) return // cancelled (Clear / new run) before we started
      set({ progress: { done: 0, total: lines.length } })

      // Index-ordered result buffer; workers fill slots and we render the
      // completed entries in order so rows never jump around.
      const results: (PipelineEntry | null)[] = new Array(lines.length).fill(null)
      let next = 0
      const worker = async () => {
        for (;;) {
          const i = next++
          if (i >= lines.length || get().runId !== runId) return
          try {
            results[i] = await api.get(`/statement-lines/${lines[i].id}/pipeline-entry`).then((r) => r.data)
          } catch {
            /* skip a line that fails to score; keep the run going */
          }
          if (get().runId !== runId) return
          set((s) => ({
            entries: results.filter((e): e is PipelineEntry => e !== null),
            progress: { total: s.progress.total, done: s.progress.done + 1 },
          }))
        }
      }
      await Promise.all(Array.from({ length: Math.min(CONCURRENCY, lines.length) }, worker))
    } catch (e: unknown) {
      if (get().runId === runId) {
        set({ notice: { kind: 'err', text: e instanceof Error ? e.message : 'Could not start the run.' } })
      }
    } finally {
      if (get().runId === runId) set({ running: false })
    }
  },
}))
