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
  contact_id: number | null
  confidence: number
  source: string
  created_at: string
}

export interface ContactDocSummary {
  id: number
  number: string | null
  issue_date: string
  total: number
  outstanding: number
  currency: string
  status: DocumentStatus
}

export type CreditDirection = 'payable' | 'receivable'
export type CreditKind = 'overpayment' | 'prepayment'

export interface ContactCreditSummary {
  id: number
  kind: CreditKind
  direction: CreditDirection
  currency: string
  original_amount: number
  outstanding: number
  status: DocumentStatus
  issue_date: string
}

export interface ContactDetail {
  contact: Contact
  invoices: ContactDocSummary[]
  bills: ContactDocSummary[]
  aliases: VendorAlias[]
  credits: ContactCreditSummary[]
}

export interface CreditAllocation {
  id: number
  target_type: string          // 'bill' | 'invoice'
  target_id: number
  target_label: string
  amount: number
  created_at: string
}

export interface Credit {
  id: number
  contact_id: number | null
  contact_name: string
  direction: CreditDirection
  kind: CreditKind
  issue_date: string
  currency: string
  original_amount: number
  allocated_amount: number
  outstanding: number
  status: DocumentStatus
  source_statement_line_id: number | null
  created_at: string
  allocations: CreditAllocation[]
}

export interface ReconciledLine {
  id: number
  date: string
  description: string
  amount: number
  direction: 'in' | 'out'
  status: string
  target_kind: string
  target_label: string
  reconciled_at: string | null
}

export interface UnreconcileResult {
  line_id: number
  reverted_label: string | null
  removed_alias: string | null
  message: string
}

export interface ContactPaymentTiming {
  contact_id: number
  observations: number
  sample_size: number
  typical_days: number | null
  window_days: number | null
  min_days: number | null
  max_days: number | null
  consistency: 'consistent' | 'variable' | null
  trend: 'steady' | 'slower' | 'faster' | null
  recent_lags: number[]
  updated_at: string | null
}

export type DocumentStatus =
  | 'draft'
  | 'awaiting_approval'
  | 'awaiting_payment'
  | 'paid'
  | 'voided'

export type StatementLineStatus =
  | 'pending'
  | 'matched'
  | 'manual'
  | 'transfer'
  | 'discussed'

export interface InvoiceLine {
  id: number
  invoice_id: number
  description: string
  quantity: number
  unit_price: number
  tax_rate: number
  line_total: number
  service_id: number | null
}

export interface Invoice {
  id: number
  number: string
  contact_id: number | null
  contact_name: string
  reference: string | null
  issue_date: string
  due_date: string | null
  subtotal: number
  tax_total: number
  total: number
  paid_amount: number
  outstanding: number
  currency: string
  status: DocumentStatus
  notes: string | null
  sent: boolean
  lines: InvoiceLine[]
  created_at: string
  updated_at: string
}

export interface InvoiceLineCreate {
  description: string
  quantity: number
  unit_price: number
  tax_rate: number
  service_id?: number | null
}

export interface InvoiceCreate {
  number: string
  contact_id?: number | null
  contact_name: string
  reference?: string | null
  issue_date: string
  due_date?: string | null
  currency?: string
  notes?: string | null
  status?: DocumentStatus
  lines: InvoiceLineCreate[]
}

export interface BillLine {
  id: number
  bill_id: number
  description: string
  quantity: number
  unit_price: number
  tax_rate: number
  line_total: number
  account_code: string | null
}

export interface Bill {
  id: number
  number: string | null
  contact_id: number | null
  contact_name: string
  reference: string | null
  issue_date: string
  due_date: string | null
  subtotal: number
  tax_total: number
  total: number
  paid_amount: number
  outstanding: number
  currency: string
  status: DocumentStatus
  notes: string | null
  lines: BillLine[]
  created_at: string
  updated_at: string
}

export interface BillLineCreate {
  description: string
  quantity: number
  unit_price: number
  tax_rate: number
  account_code?: string | null
}

export interface BillCreate {
  number?: string | null
  contact_id?: number | null
  contact_name: string
  reference?: string | null
  issue_date: string
  due_date?: string | null
  currency?: string
  notes?: string | null
  status?: DocumentStatus
  lines: BillLineCreate[]
}

export interface BankAccount {
  id: number
  name: string
  account_number: string | null
  bank_name: string | null
  currency: string
  statement_balance: number
  ooo_balance: number
  balance_difference: number
  pending_count: number
  last_imported_at: string | null
  is_active: boolean
  created_at: string
}

export interface BulkMatchItem {
  id: number
  amount: number
  label: string
}

export interface StatementLine {
  id: number
  bank_account_id: number
  date: string
  description: string
  reference: string | null
  spent: number
  received: number
  balance_after: number | null
  status: StatementLineStatus
  matched_invoice_id: number | null
  matched_bill_id: number | null
  matched_journal_id: number | null
  transfer_to_account_id: number | null
  matched_invoice_ids: BulkMatchItem[] | null
  matched_bill_ids: BulkMatchItem[] | null
  matched_credit_id: number | null
  discussion: string | null
  suggested_score: number | null
  imported_at: string
  reconciled_at: string | null
}

export interface UserProfile {
  id: number | null
  name: string
  role: string
  email: string | null
  updated_at: string
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
