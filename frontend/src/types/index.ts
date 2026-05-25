export type MatchStatus =
  | 'exact'
  | 'fuzzy'
  | 'one_to_many'
  | 'many_to_one'
  | 'possible'
  | 'unmatched'
  | 'human_corrected'

export type ContactType = 'customer' | 'supplier' | 'internal' | 'other'
export type TaxTreatment = 'exclusive' | 'inclusive' | 'exempt'
export type ServiceCategory = 'service' | 'product'

export interface RunSummary {
  run_id: string
  created_at: string
  total: number
  matched: number
  pending: number
  unmatched: number
  match_rate: number
}

export interface Match {
  id: number
  run_id: string
  bank_txn_id: string
  ledger_txn_id: string | null
  status: MatchStatus
  score: number
  reasoning_path: string
  amount_diff: number | null
  date_diff_days: number | null
  requires_human_review: boolean
  human_approved: boolean | null
  created_at: string
}

export interface Contact {
  id: number
  full_name: string
  company: string | null
  contact_type: ContactType
  email: string | null
  phone: string | null
  address: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export interface Company {
  id: number | null
  company_name: string
  about: string | null
  industry: string | null
  website: string | null
  phone: string | null
  address: string | null
  registration_number: string | null
  vat_registered: boolean
  vat_number: string | null
  tax_treatment: TaxTreatment
  updated_at: string
}

export interface VendorAlias {
  id: number
  alias: string
  canonical_name: string
  confidence: number
  source: string
  created_at: string
}

export interface DashboardStats {
  total_runs: number
  total_transactions: number
  overall_match_rate: number
  pending_review: number
  total_contacts: number
  last_run_date: string | null
}

export interface Service {
  id: number
  name: string
  description: string | null
  service_category: ServiceCategory
  vat_applicable: boolean
  created_at: string
}
