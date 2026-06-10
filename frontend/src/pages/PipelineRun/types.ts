/** Types mirroring the /statement-lines/pipeline response. Shared by the page + store. */
import type { MatchStrength } from '@/lib/match'

export interface Suggestion {
  type: 'invoice' | 'bill'
  id: number
  label: string
  contact_name: string
  date: string
  amount: number
  currency: string
  score: number
  reason: string
  method: string
}

// Steps carry per-step fields; we read them by step number, so type loosely.
export interface TraceStep {
  n: number
  title: string
  detail: string
  [k: string]: unknown
}

export interface Trace {
  input: {
    bank_description: string
    bank_amount: number
    bank_date: string
    candidate_label: string
    candidate_vendor: string
    candidate_amount: number
    candidate_date: string
  }
  steps: TraceStep[]
  final: {
    score: number
    score_pct: number
    method: string
    strength: MatchStrength
    strength_label: string
  }
}

export interface PipelineEntry {
  line: {
    id: number
    date: string
    description: string
    reference: string | null
    spent: number
    received: number
    amount: number
    direction: 'in' | 'out'
    status: string
  }
  candidate_count: number
  top_candidate: Suggestion | null
  trace: Trace | null
}

export interface RunSummaryData {
  total: number
  auto_matched: number
  needs_review: number
  unmatched: number
  match_rate: number
  bands: Record<MatchStrength | 'none', number>
  methods: Record<string, number>
}

export interface Notice {
  kind: 'ok' | 'err'
  text: string
}
