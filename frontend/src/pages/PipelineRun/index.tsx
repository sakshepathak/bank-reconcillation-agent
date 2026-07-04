/**
 * Pipeline Run — the "show your working" demo surface.
 *
 * Upload a whole bank statement + the invoices/bills it should match against,
 * then run the matching engine over EVERY line at once and watch each step of
 * the cascade and every intermediate number it computed.
 *
 * It deliberately reuses the live engine: the batch endpoint calls the same
 * get_suggestions() + explain_candidate() the Reconcile screen uses, so the
 * numbers shown here are identical to what the app actually acts on.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Upload, Play, Loader2, ChevronRight, FileText, Landmark, Receipt,
  ArrowDownLeft, ArrowUpRight, Sparkles, CheckCircle2, AlertTriangle,
  XCircle, Maximize2, Minimize2, Plus, PackageOpen, Trash2, ArrowDownUp,
} from 'lucide-react'
import { Input } from '@/components/ui/input'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { NativeSelect } from '@/components/ui/native-select'
import { cn, formatCurrency, formatDate } from '@/lib/utils'
import { humanizeUploadError } from '@/lib/upload-errors'
import type { BankAccount } from '@/types'
import type { MatchStrength } from '@/lib/match'
import { usePipelineStore } from './store'
import type { PipelineEntry, RunSummaryData, Trace, TraceStep } from './types'

// ─────────────────────────────────────────────────────────────────────────────
// Run summary (types live in ./types, run state lives in ./store)
// ─────────────────────────────────────────────────────────────────────────────

function computeSummary(entries: PipelineEntry[]): RunSummaryData {
  const bands: Record<MatchStrength | 'none', number> = { strong: 0, likely: 0, possible: 0, weak: 0, none: 0 }
  const methods: Record<string, number> = {}
  for (const e of entries) {
    if (e.trace) {
      bands[e.trace.final.strength] += 1
      methods[e.trace.final.method] = (methods[e.trace.final.method] ?? 0) + 1
    } else {
      bands.none += 1
    }
  }
  const total = entries.length
  const auto = bands.strong
  return {
    total,
    auto_matched: auto,
    needs_review: bands.likely + bands.possible + bands.weak,
    unmatched: bands.none,
    match_rate: total ? Math.round((auto / total) * 1000) / 10 : 0,
    bands,
    methods,
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Small presentational helpers
// ─────────────────────────────────────────────────────────────────────────────

const STRENGTH_VARIANT: Record<MatchStrength, 'success' | 'warning' | 'muted'> = {
  strong: 'success',
  likely: 'success',
  possible: 'warning',
  weak: 'muted',
}

const METHOD_LABEL: Record<string, string> = {
  'alias-exact': 'Known alias',
  'canonical-exact': 'Same name',
  fuzzy: 'Similar spelling',
  'fuzzy+embed': 'Similar meaning (AI)',
  'no-name': 'No name signal',
}

/** The real engine function behind each step — shown so the demo is verifiably the live code. */
const STEP_FN: Record<number, { fn: string; file: string }> = {
  1: { fn: 'canonicalize()', file: 'engine/vendor_matching/normalizer.py' },
  2: { fn: 'find_matches()', file: 'engine/vendor_matching/matcher.py' },
  3: { fn: 'similarity()', file: 'engine/vendor_matching/similarity.py' },
  4: { fn: 'embedder.cosine()', file: 'engine/vendor_matching/embedder.py' },
  5: { fn: 'find_matches()', file: 'engine/vendor_matching/matcher.py' },
  6: { fn: 'get_suggestions()', file: 'api/routers/statement_lines.py' },
  7: { fn: '_strength()', file: 'engine/vendor_matching/explain.py' },
}

function pct(v: number): string {
  return `${Math.round(v * 100)}%`
}

/** A 0..1 score bar. */
function ScoreBar({
  value, max = 1, tone = 'primary', className,
}: {
  value: number
  max?: number
  tone?: 'primary' | 'emerald' | 'amber' | 'slate' | 'indigo'
  className?: string
}) {
  const widthPct = Math.max(0, Math.min(1, value / max)) * 100
  const bg = {
    primary: 'bg-primary',
    emerald: 'bg-emerald-500',
    amber: 'bg-amber-500',
    slate: 'bg-slate-400 dark:bg-slate-500',
    indigo: 'bg-matcha-500',
  }[tone]
  return (
    <div className={cn('h-2 rounded-full bg-slate-100 dark:bg-white/10 overflow-hidden', className)}>
      <div className={cn('h-full rounded-full transition-all', bg)} style={{ width: `${widthPct}%` }} />
    </div>
  )
}

function step<T = TraceStep>(t: Trace, n: number): T {
  return (t.steps.find((s) => s.n === n) ?? { n, title: '', detail: '' }) as T
}

// ─────────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────────

export default function PipelineRun() {
  const qc = useQueryClient()
  const [showNewAcct, setShowNewAcct] = useState(false)
  const [newAcctName, setNewAcctName] = useState('')

  // Run state lives in a zustand store so it SURVIVES navigating away and back —
  // the results, progress and selection are kept until you explicitly Clear them.
  const {
    entries, progress, running, accountId, expanded, allExpanded, notice, sortDir,
    setAccountId, setNotice, setAllExpanded, toggleRow, toggleSort, run, clear,
  } = usePipelineStore()

  const summary = useMemo(() => computeSummary(entries), [entries])

  // Presentational sort by statement date. We sort a COPY so the store keeps the
  // engine's processing order intact (the run loop streams into `entries` by index).
  const sortedEntries = useMemo(() => {
    const dir = sortDir === 'asc' ? 1 : -1
    return [...entries].sort((a, b) => dir * a.line.date.localeCompare(b.line.date))
  }, [entries, sortDir])

  const { data: accounts } = useQuery<BankAccount[]>({
    queryKey: ['bank-accounts'],
    queryFn: () => api.get('/bank-accounts/').then((r) => r.data),
  })

  // Auto-select the first account so the bank-statement upload is never silently
  // locked behind a "pick an account" step the user can't see. Also re-selects a
  // valid account if the stored one no longer exists (e.g. after an org switch).
  useEffect(() => {
    if (!accounts) return
    if (accountId === null && accounts.length > 0) setAccountId(accounts[0].id)
    else if (accountId !== null && !accounts.some((a) => a.id === accountId))
      setAccountId(accounts[0]?.id ?? null)
  }, [accounts, accountId, setAccountId])

  const createAccount = useMutation({
    mutationFn: (name: string) => api.post('/bank-accounts/', { name }).then((r) => r.data as BankAccount),
    onSuccess: (acc) => {
      qc.invalidateQueries({ queryKey: ['bank-accounts'] })
      setAccountId(acc.id)
      setNewAcctName('')
      setShowNewAcct(false)
      setNotice({ kind: 'ok', text: `Created bank account “${acc.name}”. You can upload a statement now.` })
    },
    onError: (e: unknown) => setNotice({ kind: 'err', text: e instanceof Error ? e.message : 'Could not create account.' }),
  })

  // ── Uploads ────────────────────────────────────────────────────────────────
  const docInput = useRef<HTMLInputElement>(null)
  const billInput = useRef<HTMLInputElement>(null)
  const stmtInput = useRef<HTMLInputElement>(null)

  const uploadDocs = useMutation({
    mutationFn: async ({ files, kind }: { files: File[]; kind: 'invoice' | 'bill' }) => {
      let created = 0
      for (const file of files) {
        const form = new FormData()
        form.append('file', file)
        const isCsv = file.name.toLowerCase().endsWith('.csv') || file.type === 'text/csv'
        const base = kind === 'invoice' ? '/invoices' : '/bills'
        const res = await api.post(isCsv ? `${base}/upload-csv` : `${base}/upload`, form, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
        created += Array.isArray(res.data) ? res.data.length : 1
      }
      return created
    },
    onSuccess: (created, { kind }) => {
      qc.invalidateQueries({ queryKey: [kind === 'invoice' ? 'invoices' : 'bills'] })
      setNotice({ kind: 'ok', text: `Imported ${created} ${kind === 'invoice' ? 'invoice' : 'bill'}${created === 1 ? '' : 's'}.` })
    },
    onError: (e: unknown) => setNotice({ kind: 'err', text: humanizeUploadError(e instanceof Error ? e.message : String(e)) }),
  })

  const uploadStatement = useMutation({
    mutationFn: async (files: File[]) => {
      if (accountId === null) throw new Error('Pick a bank account first.')
      let created = 0
      for (const file of files) {
        const form = new FormData()
        form.append('bank_account_id', String(accountId))
        form.append('file', file)
        const res = await api.post('/statement-lines/upload', form, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
        created += Array.isArray(res.data) ? res.data.length : 1
      }
      return created
    },
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['statement-lines'] })
      setNotice({ kind: 'ok', text: `Imported ${created} statement line${created === 1 ? '' : 's'}.` })
    },
    onError: (e: unknown) => setNotice({ kind: 'err', text: humanizeUploadError(e instanceof Error ? e.message : String(e)) }),
  })

  // One-click demo. Idempotent and isolated: sample data loads into a dedicated
  // "Pipeline Demo" bank account that is RESET on every load, so repeated clicks
  // never pile up or touch your real accounts. Invoices/bills re-import by number
  // (no duplicates) and aliases are de-duped before seeding.
  const DEMO_ACCOUNT_NAME = 'Pipeline Demo (sample)'
  const loadSample = useMutation({
    mutationFn: async () => {
      // Find-or-create the dedicated demo account, and wipe its old lines.
      const accountsList: BankAccount[] = await api.get('/bank-accounts/').then((r) => r.data)
      const existingDemo = accountsList.find((a) => a.name === DEMO_ACCOUNT_NAME)
      let acctId: number
      if (existingDemo) {
        await api.post(`/bank-accounts/${existingDemo.id}/reset`)  // idempotent: clear prior demo lines
        acctId = existingDemo.id
      } else {
        const created = await api.post('/bank-accounts/', { name: DEMO_ACCOUNT_NAME }).then((r) => r.data as BankAccount)
        acctId = created.id
      }
      setAccountId(acctId)

      const fetchFile = async (name: string): Promise<File> => {
        const res = await fetch(`/sample-data/${name}`)
        if (!res.ok) throw new Error(`Sample file ${name} not found`)
        return new File([await res.blob()], name, { type: 'text/csv' })
      }
      const [inv, bill, stmt] = await Promise.all([
        fetchFile('invoices.csv'), fetchFile('bills.csv'), fetchFile('bank_statement_signed.csv'),
      ])
      const up = async (url: string, file: File, extra?: Record<string, string>) => {
        const form = new FormData()
        form.append('file', file)
        if (extra) for (const [k, v] of Object.entries(extra)) form.append(k, v)
        await api.post(url, form, { headers: { 'Content-Type': 'multipart/form-data' } })
      }
      await up('/invoices/upload-csv', inv)   // re-import updates by number (no dupes)
      await up('/bills/upload-csv', bill)     // re-import updates by number (no dupes)
      await up('/statement-lines/upload', stmt, { bank_account_id: String(acctId) })

      // Seed a few learned aliases so the Vendor Aliases page is populated and the
      // matcher visibly uses them (bank text → real invoice/bill vendor). De-dup
      // against what's already there so repeat loads don't duplicate rows.
      const SEED_ALIASES: [string, string][] = [
        ['BK COFFEE ROASTERS CAFE SUPPLIES', 'Brooklyn Coffee Roasters'],
        ['INGRAM CONTENT GRP NASHVILLE', 'Ingram Content Group'],
        ['CON EDISON ELECTRIC', 'Con Edison'],
        ['HARPERCOLLINS PUBLISHERS WIRE', 'HarperCollins'],
        ['GREENPOINT BRANCH LIBRARY ACH', 'Greenpoint Library'],
        ['WILLIAMSBURG HS PARTIAL PAYMENT', 'Williamsburg High School'],
      ]
      const existingAliases: { alias: string }[] = await api.get('/aliases/').then((r) => r.data)
      const have = new Set(existingAliases.map((a) => a.alias.toLowerCase()))
      for (const [aliasText, canonical] of SEED_ALIASES) {
        if (!have.has(aliasText.toLowerCase())) {
          try { await api.post('/aliases/', { alias: aliasText, canonical_name: canonical }) } catch { /* non-fatal */ }
        }
      }
      return acctId
    },
    onSuccess: (acctId) => {
      qc.invalidateQueries()
      setNotice({ kind: 'ok', text: 'Loaded the Brooklyn Bookstore demo into the "Pipeline Demo" account (reset on each load — nothing piles up, your real accounts are untouched). Running…' })
      run(acctId)
    },
    onError: (e: unknown) => setNotice({ kind: 'err', text: e instanceof Error ? e.message : 'Could not load sample data.' }),
  })

  const busy = uploadDocs.isPending || uploadStatement.isPending || loadSample.isPending

  const hasResults = entries.length > 0

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Pipeline Run</h1>
          <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
            Upload a bank statement and the invoices/bills it should match, then run the
            matching engine over every line at once. Each entry shows the full cascade in order —
            match the name, then check amount and date, then combine into one score — with every
            number the engine computed, the same logic the Reconcile screen uses.
          </p>
        </div>
        {hasResults && (
          <div className="flex items-center gap-2 flex-shrink-0">
            <Button variant="outline" size="sm" onClick={() => setAllExpanded(!allExpanded)}>
              {allExpanded ? <Minimize2 className="w-4 h-4 mr-1.5" /> : <Maximize2 className="w-4 h-4 mr-1.5" />}
              {allExpanded ? 'Collapse all' : 'Expand all'}
            </Button>
            <Button variant="outline" size="sm" onClick={() => clear()} title="Clear the results and progress on this page">
              <Trash2 className="w-4 h-4 mr-1.5" />
              Clear
            </Button>
          </div>
        )}
      </div>

      {/* ── 1. Load the data ─────────────────────────────────────────────────── */}
      <Card>
        <CardContent className="p-5 space-y-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-muted-foreground uppercase tracking-tight">
            <span className="w-5 h-5 rounded-full bg-primary text-primary-foreground text-[11px] grid place-items-center">1</span>
            Load the data
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <UploadTile
              icon={Receipt}
              label="Invoices"
              hint="Money you're owed · PDF or CSV"
              busy={uploadDocs.isPending && uploadDocs.variables?.kind === 'invoice'}
              onClick={() => docInput.current?.click()}
            />
            <UploadTile
              icon={FileText}
              label="Bills"
              hint="Money you owe · PDF or CSV"
              busy={uploadDocs.isPending && uploadDocs.variables?.kind === 'bill'}
              onClick={() => billInput.current?.click()}
            />
            <UploadTile
              icon={Landmark}
              label="Bank statement"
              hint={accountId === null ? 'Create or pick an account below ↓' : 'PDF or CSV'}
              disabled={accountId === null}
              busy={uploadStatement.isPending}
              onClick={() => stmtInput.current?.click()}
            />
          </div>

          {/* hidden inputs */}
          <input
            ref={docInput} type="file" accept=".pdf,.csv,image/*" multiple hidden
            onChange={(e) => { const files = Array.from(e.target.files ?? []); e.target.value = ''; if (files.length) uploadDocs.mutate({ files, kind: 'invoice' }) }}
          />
          <input
            ref={billInput} type="file" accept=".pdf,.csv,image/*" multiple hidden
            onChange={(e) => { const files = Array.from(e.target.files ?? []); e.target.value = ''; if (files.length) uploadDocs.mutate({ files, kind: 'bill' }) }}
          />
          <input
            ref={stmtInput} type="file" accept=".pdf,.csv" multiple hidden
            onChange={(e) => { const files = Array.from(e.target.files ?? []); e.target.value = ''; if (files.length) uploadStatement.mutate(files) }}
          />

          <div className="flex flex-wrap items-end gap-3 pt-1">
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground">Bank account</label>
              <NativeSelect
                value={showNewAcct ? '__new__' : (accountId ?? '')}
                onChange={(e) => {
                  if (e.target.value === '__new__') { setShowNewAcct(true) }
                  else { setShowNewAcct(false); setAccountId(e.target.value ? Number(e.target.value) : null) }
                }}
                className="w-56"
              >
                {(!accounts || accounts.length === 0) && <option value="">No accounts yet</option>}
                {accounts?.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
                <option value="__new__">＋ New account…</option>
              </NativeSelect>
            </div>

            {showNewAcct && (
              <div className="flex items-end gap-2">
                <div className="space-y-1">
                  <label className="text-xs font-medium text-muted-foreground">New account name</label>
                  <Input
                    value={newAcctName}
                    onChange={(e) => setNewAcctName(e.target.value)}
                    placeholder="e.g. Current Account"
                    className="w-48"
                    onKeyDown={(e) => { if (e.key === 'Enter' && newAcctName.trim()) createAccount.mutate(newAcctName.trim()) }}
                  />
                </div>
                <Button
                  variant="outline"
                  disabled={!newAcctName.trim() || createAccount.isPending}
                  onClick={() => createAccount.mutate(newAcctName.trim())}
                >
                  {createAccount.isPending ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <Plus className="w-4 h-4 mr-1.5" />}
                  Create
                </Button>
              </div>
            )}

            <Button onClick={() => run()} disabled={busy || running}>
              {running ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <Play className="w-4 h-4 mr-1.5" />}
              {running ? `Running… ${progress.done}/${progress.total}` : 'Run pipeline'}
            </Button>

            <Button variant="outline" onClick={() => loadSample.mutate()} disabled={busy || running} title="Create a demo account and load the Brooklyn Bookstore invoices, bills and statement, then run">
              {loadSample.isPending ? <Loader2 className="w-4 h-4 mr-1.5 animate-spin" /> : <PackageOpen className="w-4 h-4 mr-1.5" />}
              Load demo data
            </Button>
          </div>

          {/* Live progress bar */}
          {running && progress.total > 0 && (
            <div className="space-y-1">
              <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full bg-primary transition-all duration-300"
                  style={{ width: `${(progress.done / progress.total) * 100}%` }}
                />
              </div>
              <p className="text-[11px] text-muted-foreground">
                Scoring line {Math.min(progress.done + 1, progress.total)} of {progress.total} — running the full cascade on each…
              </p>
            </div>
          )}

          {notice && (
            <p className={cn('text-sm', notice.kind === 'ok' ? 'text-emerald-700' : 'text-amber-700')}>
              {notice.text}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Empty state — run finished with nothing to process */}
      {!running && !hasResults && progress.total === 0 && progress.done === 0 && (
        <Card><CardContent className="p-10 text-center text-muted-foreground text-sm">
          Upload invoices/bills and a bank statement, then hit <span className="font-medium">Run pipeline</span> to watch the engine score every line.
        </CardContent></Card>
      )}
      {!running && !hasResults && progress.total === 0 && progress.done > 0 && (
        <Card><CardContent className="p-10 text-center text-muted-foreground">
          No statement lines to process. Upload a bank statement above, then run again.
        </CardContent></Card>
      )}

      {/* ── 2. Run summary ───────────────────────────────────────────────────── */}
      {hasResults && <RunSummary summary={summary} live={running} processed={progress.done} total={progress.total} />}

      {/* ── 3. Per-entry results (stream in live) ────────────────────────────── */}
      {hasResults && (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2 px-1">
            <div className="flex items-center gap-2 text-sm font-semibold text-muted-foreground uppercase tracking-tight">
              <span className="w-5 h-5 rounded-full bg-primary text-primary-foreground text-[11px] grid place-items-center">3</span>
              Every entry, step by step
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => toggleSort()}
              title="Sort the results by statement date"
            >
              <ArrowDownUp className="w-3.5 h-3.5 mr-1.5" />
              {sortDir === 'asc' ? 'Oldest first' : 'Newest first'}
            </Button>
          </div>
          {sortedEntries.map((entry) => (
            <EntryRow
              key={entry.line.id}
              entry={entry}
              open={allExpanded || expanded.has(entry.line.id)}
              onToggle={() => toggleRow(entry.line.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Upload tile
// ─────────────────────────────────────────────────────────────────────────────

function UploadTile({
  icon: Icon, label, hint, onClick, busy, disabled,
}: {
  icon: typeof Upload
  label: string
  hint: string
  onClick: () => void
  busy?: boolean
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || busy}
      className={cn(
        'flex items-center gap-3 rounded-lg border border-dashed px-4 py-3 text-left transition-colors',
        disabled ? 'opacity-50 cursor-not-allowed' : 'hover:border-primary hover:bg-primary/5',
      )}
    >
      <div className="w-9 h-9 rounded-lg bg-primary/10 grid place-items-center flex-shrink-0">
        {busy ? <Loader2 className="w-4 h-4 text-primary animate-spin" /> : <Icon className="w-4 h-4 text-primary" />}
      </div>
      <div className="min-w-0">
        <p className="text-sm font-medium">{label}</p>
        <p className="text-[11px] text-muted-foreground truncate">{hint}</p>
      </div>
      <Upload className="w-4 h-4 text-muted-foreground ml-auto flex-shrink-0" />
    </button>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Run summary bar
// ─────────────────────────────────────────────────────────────────────────────

function RunSummary({ summary, live, processed, total }: { summary: RunSummaryData; live: boolean; processed: number; total: number }) {
  const stats = [
    { label: live ? `Lines processed (${processed}/${total})` : 'Lines processed', value: summary.total, icon: FileText, tone: 'text-foreground' },
    { label: 'Auto-match quality', value: summary.auto_matched, icon: CheckCircle2, tone: 'text-emerald-600' },
    { label: 'Need review', value: summary.needs_review, icon: AlertTriangle, tone: 'text-amber-600' },
    { label: 'No candidate', value: summary.unmatched, icon: XCircle, tone: 'text-muted-foreground' },
  ]
  const methodEntries = Object.entries(summary.methods).filter(([m]) => m !== 'no-name')

  return (
    <Card>
      <CardContent className="p-5 space-y-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-muted-foreground uppercase tracking-tight">
          <span className="w-5 h-5 rounded-full bg-primary text-primary-foreground text-[11px] grid place-items-center">2</span>
          Run summary
        </div>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {stats.map((s) => (
            <div key={s.label}>
              <div className="flex items-center gap-1.5">
                <s.icon className={cn('w-4 h-4', s.tone)} />
                <span className={cn('text-2xl font-bold', s.tone)}>{s.value}</span>
              </div>
              <p className="text-[11px] text-muted-foreground mt-0.5">{s.label}</p>
            </div>
          ))}
          <div>
            <div className="flex items-center gap-1.5">
              <Sparkles className="w-4 h-4 text-primary" />
              <span className="text-2xl font-bold text-primary">{summary.match_rate}%</span>
            </div>
            <p className="text-[11px] text-muted-foreground mt-0.5">Auto-match rate</p>
          </div>
        </div>

        {methodEntries.length > 0 && (
          <div className="pt-1 border-t">
            <p className="text-[11px] text-muted-foreground mb-2 mt-3">Which tier did the work</p>
            <div className="flex flex-wrap gap-2">
              {methodEntries.map(([m, count]) => (
                <Badge key={m} variant="info">
                  {METHOD_LABEL[m] ?? m} · {count}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// One statement-line entry: collapsed row + expandable step detail
// ─────────────────────────────────────────────────────────────────────────────

function EntryRow({ entry, open, onToggle }: { entry: PipelineEntry; open: boolean; onToggle: () => void }) {
  const { line, top_candidate, trace } = entry
  const strength = trace?.final.strength
  const variant = strength ? STRENGTH_VARIANT[strength] : 'muted'
  const currency = top_candidate?.currency || 'GBP'

  return (
    <Card className={cn('overflow-hidden', open && 'ring-1 ring-primary/30')}>
      {/* Collapsed header row */}
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-muted/40 transition-colors"
      >
        <ChevronRight className={cn('w-4 h-4 text-muted-foreground transition-transform flex-shrink-0', open && 'rotate-90')} />

        {/* Direction */}
        <div className={cn('w-8 h-8 rounded-lg grid place-items-center flex-shrink-0',
          line.direction === 'in' ? 'bg-emerald-100' : 'bg-rose-100')}>
          {line.direction === 'in'
            ? <ArrowDownLeft className="w-4 h-4 text-emerald-600" />
            : <ArrowUpRight className="w-4 h-4 text-rose-600" />}
        </div>

        {/* Bank line */}
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium truncate">{line.description || '—'}</p>
          <p className="text-[11px] text-muted-foreground">{formatDate(line.date)} · {formatCurrency(line.amount, currency)}</p>
        </div>

        {/* Matched candidate */}
        <div className="hidden sm:block min-w-0 flex-1 text-right">
          {top_candidate ? (
            <>
              <p className="text-sm truncate">{top_candidate.contact_name} <span className="text-muted-foreground">· {top_candidate.label}</span></p>
              <p className="text-[11px] text-muted-foreground">{METHOD_LABEL[top_candidate.method] ?? top_candidate.method}</p>
            </>
          ) : (
            <p className="text-sm text-muted-foreground italic">no candidate</p>
          )}
        </div>

        {/* Verdict */}
        <div className="flex items-center gap-2 flex-shrink-0 w-24 justify-end">
          {trace ? (
            <Badge variant={variant}>{trace.final.score_pct}% {trace.final.strength_label.replace(' match', '')}</Badge>
          ) : (
            <Badge variant="muted">—</Badge>
          )}
        </div>
      </button>

      {/* Cascade strip (always visible, compact) */}
      {trace && <CascadeStrip trace={trace} />}

      {/* Full step detail */}
      {open && trace && (
        <div className="border-t bg-muted/20 p-4">
          <NarrativePanel trace={trace} />
          <StepDetail trace={trace} currency={currency} />
        </div>
      )}
    </Card>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Cascade strip — the full decision flow at a glance, IN ORDER:
// match the name (normalise → alias → spelling → meaning → best name),
// then check amount and date, then combine all three into the final score.
// ─────────────────────────────────────────────────────────────────────────────

function CascadeStrip({ trace }: { trace: Trace }) {
  const s1 = step(trace, 1)
  const s2 = step(trace, 2)
  const s3 = step(trace, 3)
  const s4 = step(trace, 4)
  const s5 = step(trace, 5)
  const s6 = step(trace, 6) // composite: carries amount + date + name breakdown

  const chips: { key: string; group: string; title: string; result: string; dim?: boolean }[] = [
    { key: 'norm', group: 'name', title: 'Normalise', result: String(s1.candidate_canonical ?? '—') },
    { key: 'alias', group: 'name', title: 'Alias', result: s2.hit ? 'matched' : 'none', dim: !s2.hit },
    { key: 'spell', group: 'name', title: 'Spelling', result: s3.metrics ? pct(s3.composite as number) : '—' },
    {
      key: 'mean', group: 'name', title: 'Meaning (AI)',
      result: s4.fired ? (s4.cosine != null ? pct(s4.cosine as number) : 'no signal') : 'skipped',
      dim: !s4.fired,
    },
    { key: 'name', group: 'name', title: 'Best name', result: pct(s5.name_score as number) },
    { key: 'amount', group: 'amt', title: 'Amount', result: String(s6.amount_reason ?? '—'), dim: (s6.amount_component as number) === 0 },
    { key: 'date', group: 'amt', title: 'Date', result: String(s6.date_reason ?? '—'), dim: (s6.date_component as number) === 0 },
    { key: 'score', group: 'total', title: 'Final score', result: pct(s6.total as number) },
  ]

  return (
    <div className="flex items-stretch gap-1 px-4 pb-3 overflow-x-auto">
      {chips.map((c, i) => (
        <div key={c.key} className="flex items-center gap-1">
          <div className={cn(
            'rounded-md border px-2.5 py-1.5 min-w-[92px] bg-background',
            c.group === 'total' && 'border-primary/40 bg-primary/5',
            c.dim && 'opacity-50',
          )}>
            <p className="text-[10px] text-muted-foreground leading-none">{c.title}</p>
            <p className="text-xs font-semibold mt-1 truncate max-w-[130px]">{c.result}</p>
          </div>
          {i < chips.length - 1 && <ChevronRight className="w-3 h-3 text-muted-foreground/50 flex-shrink-0" />}
        </div>
      ))}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Full step-by-step detail (dense)
// ─────────────────────────────────────────────────────────────────────────────

function StepCard({ n, title, detail, children }: { n: number; title: string; detail: string; children: ReactNode }) {
  const fn = STEP_FN[n]
  return (
    <div className="rounded-lg border bg-background p-3">
      <div className="flex items-baseline gap-2">
        <span className="w-5 h-5 rounded-full bg-primary/10 text-primary text-[11px] font-bold grid place-items-center flex-shrink-0">{n}</span>
        <p className="text-sm font-semibold">{title}</p>
        {fn && (
          <code className="ml-auto text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded font-mono whitespace-nowrap" title={fn.file}>
            ƒ {fn.fn}
          </code>
        )}
      </div>
      <p className="text-[11px] text-muted-foreground mt-1 mb-2.5 leading-snug">{detail}</p>
      {children}
    </div>
  )
}

/** LLM-written plain-English narration of how this one match cascaded. */
function NarrativePanel({ trace }: { trace: Trace }) {
  const q = useQuery<{ narrative: string; provider: string; model: string }>({
    queryKey: ['narrate', trace.input.bank_description, trace.input.candidate_label, trace.final.score],
    queryFn: () => api.post('/statement-lines/narrate', trace).then((r) => r.data),
    staleTime: Infinity,
    retry: 1,
  })
  return (
    <div className="rounded-lg border border-primary/20 bg-primary/5 p-3 mb-3">
      <div className="flex items-center gap-1.5 mb-1.5">
        <Sparkles className="w-3.5 h-3.5 text-primary" />
        <span className="text-xs font-semibold text-primary">How it cascaded — in plain English</span>
        {q.data && <span className="text-[10px] text-muted-foreground ml-auto">generated by {q.data.provider}</span>}
      </div>
      {q.isLoading ? (
        <p className="text-xs text-muted-foreground flex items-center gap-1.5">
          <Loader2 className="w-3 h-3 animate-spin" /> Asking the model to narrate this match…
        </p>
      ) : q.isError ? (
        <p className="text-xs text-muted-foreground">Couldn't generate a narrative right now (model unavailable).</p>
      ) : (
        <p className="text-[13px] leading-relaxed text-foreground/90">{q.data?.narrative}</p>
      )}
    </div>
  )
}

function StepDetail({ trace, currency }: { trace: Trace; currency: string }) {
  const s1 = step(trace, 1)
  const s2 = step(trace, 2)
  const s3 = step(trace, 3)
  const s4 = step(trace, 4)
  const s5 = step(trace, 5)
  const s6 = step(trace, 6)

  const metrics = s3.metrics as Record<string, number> | null
  const weights = s3.weights as Record<string, number>
  const composite = s3.composite as number

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
      {/* Step 1 — Normalise */}
      <StepCard n={1} title="Normalise both names" detail="Strip processor prefixes, bank noise, txn IDs and suffixes; uppercase and collapse.">
        <div className="space-y-1.5 text-xs font-mono">
          <NormRow label="bank" raw={String(s1.bank_raw)} canon={String(s1.bank_canonical)} />
          <NormRow label="cand" raw={String(s1.candidate_raw)} canon={String(s1.candidate_canonical)} />
        </div>
      </StepCard>

      {/* Step 2 — Alias */}
      <StepCard n={2} title="Alias lookup (learned)" detail="Exact O(1) hit from aliases you've trained on previous reconciliations.">
        {s2.hit ? (
          <Badge variant="success">matched → {String(s2.resolved_to)}</Badge>
        ) : (
          <p className="text-xs text-muted-foreground">miss — no learned alias for this description.</p>
        )}
      </StepCard>

      {/* Step 3 — Lexical */}
      <StepCard n={3} title="Spelling similarity" detail="Weighted blend of four fuzzy-string metrics on the cleaned names.">
        {metrics ? (
          <div className="space-y-1.5">
            {(['jaro_winkler', 'token_set', 'token_sort', 'partial'] as const).map((k) => (
              <div key={k} className="grid grid-cols-[100px_1fr_auto] items-center gap-2 text-[11px]">
                <span className="text-muted-foreground">{k.replace('_', '-')}</span>
                <ScoreBar value={metrics[k]} tone="slate" />
                <span className="font-mono tabular-nums w-24 text-right">
                  {metrics[k].toFixed(2)} ×{weights[k].toFixed(2)} = {(metrics[k] * weights[k]).toFixed(2)}
                </span>
              </div>
            ))}
            <div className="flex items-center justify-between pt-1.5 mt-1 border-t">
              <span className="text-xs font-semibold">composite</span>
              <span className="text-xs font-bold font-mono">{composite.toFixed(3)}</span>
            </div>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">no candidate to score.</p>
        )}
      </StepCard>

      {/* Step 4 — Embedding */}
      <StepCard n={4} title="Meaning check (AI embedding)" detail="Only fires when spelling isn't already locked in. A BGE-small vector cosine catches meaning that spelling misses.">
        {!s4.fired ? (
          <p className="text-xs text-muted-foreground">skipped — spelling already locked it in (≥0.95).</p>
        ) : s4.cosine == null ? (
          <p className="text-xs text-muted-foreground">fired, but the model returned no signal.</p>
        ) : (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-[11px]">
              <span className="text-muted-foreground w-24">cosine similarity</span>
              <ScoreBar value={s4.cosine as number} tone="indigo" />
              <span className="font-mono tabular-nums w-10 text-right">{(s4.cosine as number).toFixed(2)}</span>
            </div>
            <p className="text-[11px]">
              {(s4.cosine as number) >= (s4.floor as number)
                ? <span className="text-emerald-700">≥ {String(s4.floor)} floor → the meaning match counts</span>
                : <span className="text-muted-foreground">&lt; {String(s4.floor)} floor → too weak to use</span>}
            </p>
          </div>
        )}
      </StepCard>

      {/* Step 5 — Ensemble */}
      <StepCard n={5} title="Best signal wins" detail="Final name score = the strongest of alias, spelling, and meaning. The winning method is recorded.">
        <div className="flex items-center gap-2 text-[11px]">
          <span className="text-muted-foreground w-20">name score</span>
          <ScoreBar value={s5.name_score as number} tone="primary" />
          <span className="font-mono tabular-nums w-10 text-right">{(s5.name_score as number).toFixed(2)}</span>
        </div>
        <p className="text-[11px] mt-2">
          winning method: <Badge variant="secondary">{METHOD_LABEL[String(s5.method)] ?? String(s5.method)}</Badge>
        </p>
      </StepCard>

      {/* Step 6 — Composite */}
      <StepCard n={6} title="Composite match score" detail="Amount (max 0.50) + date (max 0.20) + name × 0.30 — the score the app acts on.">
        <CompositeBar
          amount={s6.amount_component as number}
          date={s6.date_component as number}
          name={s6.name_component as number}
          total={s6.total as number}
        />
        <div className="grid grid-cols-3 gap-2 mt-2.5 text-[11px]">
          <CompCell label="Amount" value={s6.amount_component as number} reason={String(s6.amount_reason)} tone="text-emerald-700" />
          <CompCell label="Date" value={s6.date_component as number} reason={String(s6.date_reason)} tone="text-matcha-700" />
          <CompCell label={`Name ×0.30`} value={s6.name_component as number} reason={`raw ${(s6.name_raw as number).toFixed(2)}`} tone="text-primary" />
        </div>
      </StepCard>

      {/* Step 7 — Verdict (full width) */}
      <div className="lg:col-span-2">
        <StepCard n={7} title="Verdict" detail="Band the composite score; ≥90% is auto-approve quality, anything lower waits for a human.">
          <VerdictRuler trace={trace} />
        </StepCard>
      </div>

      {/* Input footer */}
      <div className="lg:col-span-2 text-[11px] text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 px-1">
        <span>Bank: <span className="font-mono">{trace.input.bank_description}</span> · {formatCurrency(trace.input.bank_amount, currency)} · {formatDate(trace.input.bank_date)}</span>
        <span>Candidate: <span className="font-mono">{trace.input.candidate_vendor}</span> ({trace.input.candidate_label}) · {formatCurrency(trace.input.candidate_amount, currency)} · {formatDate(trace.input.candidate_date)}</span>
      </div>
    </div>
  )
}

function NormRow({ label, raw, canon }: { label: string; raw: string; canon: string }) {
  return (
    <div>
      <span className="text-muted-foreground">{label}: </span>
      <span className="text-amber-700">{raw || '∅'}</span>
      <span className="text-muted-foreground"> → </span>
      <span className="text-emerald-700 font-semibold">{canon || '∅'}</span>
    </div>
  )
}

function CompCell({ label, value, reason, tone }: { label: string; value: number; reason: string; tone: string }) {
  return (
    <div className="rounded-md bg-muted/50 px-2 py-1.5">
      <p className="text-muted-foreground">{label}</p>
      <p className={cn('font-bold font-mono', tone)}>+{value.toFixed(2)}</p>
      <p className="text-muted-foreground truncate" title={reason}>{reason}</p>
    </div>
  )
}

/** Stacked bar showing how amount + date + name sum to the composite. */
function CompositeBar({ amount, date, name, total }: { amount: number; date: number; name: number; total: number }) {
  return (
    <div>
      <div className="flex h-4 rounded-full overflow-hidden bg-slate-100">
        <div className="bg-emerald-500 h-full" style={{ width: `${amount * 100}%` }} title={`amount ${amount.toFixed(2)}`} />
        <div className="bg-matcha-500 h-full" style={{ width: `${date * 100}%` }} title={`date ${date.toFixed(2)}`} />
        <div className="bg-primary h-full" style={{ width: `${name * 100}%` }} title={`name ${name.toFixed(2)}`} />
      </div>
      <div className="flex justify-between text-[11px] mt-1">
        <span className="text-muted-foreground">0.00</span>
        <span className="font-bold font-mono">total = {total.toFixed(2)}</span>
        <span className="text-muted-foreground">1.00</span>
      </div>
    </div>
  )
}

/** Places the score on the 0.65 / 0.75 / 0.90 threshold ruler. */
function VerdictRuler({ trace }: { trace: Trace }) {
  const score = trace.final.score
  const strength = trace.final.strength
  const variant = STRENGTH_VARIANT[strength]
  const auto = score >= 0.9
  const marks = [
    { at: 0.65, label: 'Possible' },
    { at: 0.75, label: 'Likely' },
    { at: 0.9, label: 'Strong' },
  ]
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <Badge variant={variant} className="text-sm px-3 py-1">{trace.final.score_pct}% · {trace.final.strength_label}</Badge>
        <span className={cn('text-xs font-medium', auto ? 'text-emerald-700' : 'text-amber-700')}>
          {auto ? 'Auto-approve quality' : 'Needs human review'}
        </span>
      </div>
      <div className="relative h-9">
        {/* track */}
        <div className="absolute inset-x-0 top-3 h-2 rounded-full bg-gradient-to-r from-slate-200 via-amber-200 to-emerald-300" />
        {/* threshold marks */}
        {marks.map((m) => (
          <div key={m.at} className="absolute top-0 -translate-x-1/2 text-center" style={{ left: `${m.at * 100}%` }}>
            <div className="w-px h-5 bg-slate-400 mx-auto" />
            <span className="text-[9px] text-muted-foreground">{m.label}</span>
          </div>
        ))}
        {/* score pointer */}
        <div className="absolute top-1.5 -translate-x-1/2" style={{ left: `${Math.min(1, score) * 100}%` }}>
          <div className="w-3 h-3 rounded-full bg-primary ring-2 ring-background shadow" />
        </div>
      </div>
    </div>
  )
}
