import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Plus, X, Landmark, Upload, Loader2, AlertCircle,
  ArrowRight, Check, Building2, Eye, RotateCcw, Trash2,
} from 'lucide-react'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { cn, formatCurrency, formatDate } from '@/lib/utils'
import type { BankAccount, StatementLine } from '@/types'

type UploadState = {
  accountId: number
  filename: string
  done: boolean
  error: string | null
  linesAdded: number
} | null

const CURRENCIES = ['GBP', 'USD', 'EUR', 'INR', 'AED', 'CAD', 'AUD']

export default function BankAccountsPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [panelOpen, setPanelOpen] = useState(false)
  const [previewAccountId, setPreviewAccountId] = useState<number | null>(null)
  const [uploadingFor, setUploadingFor] = useState<UploadState>(null)
  const [confirming, setConfirming] = useState<{ accountId: number; action: 'reset' | 'delete' } | null>(null)
  const fileRefs = useRef<Record<number, HTMLInputElement | null>>({})

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['bank-accounts'] })
    queryClient.invalidateQueries({ queryKey: ['statement-lines'] })
    queryClient.invalidateQueries({ queryKey: ['invoices'] })
    queryClient.invalidateQueries({ queryKey: ['bills'] })
    queryClient.invalidateQueries({ queryKey: ['exceptions'] })
  }

  const resetMutation = useMutation({
    mutationFn: (accountId: number) => api.post(`/bank-accounts/${accountId}/reset`),
    onSuccess: () => {
      setConfirming(null)
      invalidateAll()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (accountId: number) => api.delete(`/bank-accounts/${accountId}`),
    onSuccess: () => {
      setConfirming(null)
      invalidateAll()
    },
  })

  const [form, setForm] = useState({
    name: '',
    account_number: '',
    bank_name: '',
    currency: 'GBP',
    statement_balance: 0,
    ooo_balance: 0,
  })

  const { data: accounts, isLoading } = useQuery<BankAccount[]>({
    queryKey: ['bank-accounts'],
    queryFn: () => api.get('/bank-accounts/').then((r) => r.data),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      api.post('/bank-accounts/', {
        ...form,
        account_number: form.account_number || null,
        bank_name: form.bank_name || null,
      }),
    onSuccess: () => {
      closePanel()
      queryClient.invalidateQueries({ queryKey: ['bank-accounts'] })
    },
  })

  const openCreate = () => {
    setForm({
      name: '', account_number: '', bank_name: '', currency: 'GBP',
      statement_balance: 0, ooo_balance: 0,
    })
    setPanelOpen(true)
  }

  const closePanel = () => setPanelOpen(false)

  const handleStatementUpload = async (accountId: number, fileList: FileList | null) => {
    if (!fileList || !fileList.length) return
    const file = fileList[0]
    setUploadingFor({ accountId, filename: file.name, done: false, error: null, linesAdded: 0 })

    const form = new FormData()
    form.append('bank_account_id', String(accountId))
    form.append('file', file)

    try {
      const res = await api.post('/statement-lines/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setUploadingFor({
        accountId, filename: file.name, done: true, error: null,
        linesAdded: Array.isArray(res.data) ? res.data.length : 0,
      })
      queryClient.invalidateQueries({ queryKey: ['bank-accounts'] })
      setTimeout(() => setUploadingFor(null), 2500)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setUploadingFor({ accountId, filename: file.name, done: true, error: msg, linesAdded: 0 })
    }

    const input = fileRefs.current[accountId]
    if (input) input.value = ''
  }

  const goReconcile = (id: number) => navigate(`/reconciliation?account=${id}`)

  // Top-level "drop a CSV/PDF and we'll figure out the account" import.
  // Derives the account name from the filename so the user fills in nothing.
  const topLevelFileRef = useRef<HTMLInputElement>(null)

  const handleTopLevelImport = async (files: FileList | null) => {
    if (!files || !files[0]) return
    const file = files[0]

    // Turn "TIDE BANK STATEMENT.csv" into "Tide Bank Statement"
    const baseName = file.name.replace(/\.[^.]+$/, '').replace(/[_-]/g, ' ').trim()
    const accountName =
      baseName
        .split(/\s+/)
        .filter(Boolean)
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
        .join(' ') || 'Imported Account'

    setUploadingFor({ accountId: -1, filename: file.name, done: false, error: null, linesAdded: 0 })

    try {
      const accRes = await api.post('/bank-accounts/', {
        name: accountName,
        currency: 'GBP',
        statement_balance: 0,
        ooo_balance: 0,
      })
      const accountId = accRes.data.id

      const form = new FormData()
      form.append('bank_account_id', String(accountId))
      form.append('file', file)
      const upRes = await api.post('/statement-lines/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })

      setUploadingFor({
        accountId, filename: file.name, done: true, error: null,
        linesAdded: Array.isArray(upRes.data) ? upRes.data.length : 0,
      })
      invalidateAll()
      setTimeout(() => setUploadingFor(null), 2500)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setUploadingFor({ accountId: -1, filename: file.name, done: true, error: msg, linesAdded: 0 })
    }

    if (topLevelFileRef.current) topLevelFileRef.current.value = ''
  }

  const canSave = form.name.trim().length > 0

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Bank Accounts</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Statement balance (what the bank says) vs OOO balance (what we tracked).
            The gap is what reconciliation closes.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={topLevelFileRef}
            type="file"
            accept=".csv,.pdf,text/csv,application/pdf"
            className="hidden"
            onChange={(e) => handleTopLevelImport(e.target.files)}
          />
          <Button
            size="sm"
            variant="outline"
            onClick={() => topLevelFileRef.current?.click()}
            disabled={uploadingFor !== null && !uploadingFor.done}
          >
            <Upload className="w-3.5 h-3.5 mr-1.5" />
            Import statement
          </Button>
          <Button size="sm" onClick={openCreate}>
            <Plus className="w-3.5 h-3.5 mr-1.5" />
            New Account
          </Button>
        </div>
      </div>

      {/* Account cards */}
      {isLoading ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {Array.from({ length: 2 }).map((_, i) => (
            <Skeleton key={i} className="h-48 w-full" />
          ))}
        </div>
      ) : !accounts?.length ? (
        <Card>
          <CardContent className="py-12 text-center">
            <Landmark className="w-8 h-8 text-muted-foreground mx-auto mb-3 opacity-40" />
            <p className="text-sm text-muted-foreground mb-4">
              No bank accounts yet. Drop a CSV or PDF statement to get started —
              we'll create the account automatically.
            </p>
            <div className="flex items-center justify-center gap-2">
              <Button
                size="sm"
                onClick={() => topLevelFileRef.current?.click()}
                disabled={uploadingFor !== null && !uploadingFor.done}
              >
                <Upload className="w-3.5 h-3.5 mr-1.5" />
                Import statement
              </Button>
              <Button size="sm" variant="outline" onClick={openCreate}>
                <Plus className="w-3.5 h-3.5 mr-1.5" />
                Add manually
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {accounts.map((acc) => {
            const reconciled = Math.abs(acc.balance_difference) < 0.01
            return (
              <Card key={acc.id} className="overflow-hidden">
                <CardContent className="p-4">
                  {/* Header */}
                  <div className="flex items-start justify-between gap-3 mb-4">
                    <div className="min-w-0">
                      <p className="font-semibold text-sm truncate">{acc.name}</p>
                      <p className="text-xs text-muted-foreground font-mono mt-0.5">
                        {acc.bank_name && `${acc.bank_name} · `}
                        {acc.account_number ?? 'No account number'}
                      </p>
                    </div>
                    <Badge variant={reconciled ? 'success' : 'warning'}>
                      {reconciled ? 'Reconciled' : `${acc.pending_count} pending`}
                    </Badge>
                  </div>

                  {/* Balances */}
                  <div className="grid grid-cols-2 gap-4 mb-3">
                    <div>
                      <p className="text-lg font-bold font-mono">
                        {formatCurrency(acc.statement_balance, acc.currency)}
                      </p>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        Statement balance
                        {acc.last_imported_at && (
                          <>
                            {' '}<span className="opacity-70">({formatDate(acc.last_imported_at)})</span>
                          </>
                        )}
                      </p>
                    </div>
                    <div>
                      <p className="text-lg font-bold font-mono">
                        {formatCurrency(acc.ooo_balance, acc.currency)}
                      </p>
                      <p className="text-xs text-muted-foreground mt-0.5">OOO balance</p>
                    </div>
                  </div>

                  {/* Difference */}
                  <div
                    className={cn(
                      'rounded-md px-3 py-2 mb-4 text-xs flex items-center justify-between',
                      reconciled
                        ? 'bg-emerald-50 text-emerald-700'
                        : 'bg-amber-50 text-amber-700',
                    )}
                  >
                    <span>Balance difference</span>
                    <span className="font-mono font-bold">
                      {reconciled ? (
                        <>
                          <Check className="w-3 h-3 inline mr-1" />
                          {formatCurrency(0, acc.currency)}
                        </>
                      ) : (
                        formatCurrency(acc.balance_difference, acc.currency)
                      )}
                    </span>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2">
                    {acc.pending_count > 0 && (
                      <Button size="sm" className="flex-1" onClick={() => goReconcile(acc.id)}>
                        Reconcile {acc.pending_count} items
                        <ArrowRight className="w-3.5 h-3.5 ml-1.5" />
                      </Button>
                    )}
                    <input
                      ref={(el) => { fileRefs.current[acc.id] = el }}
                      type="file"
                      accept=".csv,.pdf,text/csv,application/pdf"
                      className="hidden"
                      onChange={(e) => handleStatementUpload(acc.id, e.target.files)}
                    />
                    <Button
                      size="sm"
                      variant="outline"
                      className={acc.pending_count === 0 ? 'flex-1' : ''}
                      onClick={() => fileRefs.current[acc.id]?.click()}
                      disabled={uploadingFor?.accountId === acc.id && !uploadingFor.done}
                    >
                      <Upload className="w-3.5 h-3.5 mr-1.5" />
                      Import statement
                    </Button>
                  </div>

                  {/* Footer: View / Reset / Delete with inline confirmations */}
                  <div className="mt-3 pt-3 border-t">
                    {confirming?.accountId === acc.id && confirming.action === 'reset' ? (
                      <div className="space-y-2">
                        <p className="text-xs text-amber-900">
                          Delete all {acc.pending_count > 0 ? `${acc.pending_count}+ ` : ''}statement lines and
                          zero both balances? Reconciled invoices/bills will flip back to
                          AWAITING_PAYMENT. <strong>Cannot be undone.</strong>
                        </p>
                        <div className="flex items-center gap-2">
                          <Button
                            size="sm"
                            variant="destructive"
                            className="h-7 text-xs flex-1"
                            onClick={() => resetMutation.mutate(acc.id)}
                            disabled={resetMutation.isPending}
                          >
                            {resetMutation.isPending ? 'Resetting…' : 'Yes, reset'}
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 text-xs"
                            onClick={() => setConfirming(null)}
                          >
                            Cancel
                          </Button>
                        </div>
                      </div>
                    ) : confirming?.accountId === acc.id && confirming.action === 'delete' ? (
                      <div className="space-y-2">
                        <p className="text-xs text-rose-900">
                          Delete this bank account <strong>and</strong> all its statement lines.
                          Side effects on invoices/bills will be reversed.
                          <strong> Cannot be undone.</strong>
                        </p>
                        <div className="flex items-center gap-2">
                          <Button
                            size="sm"
                            variant="destructive"
                            className="h-7 text-xs flex-1"
                            onClick={() => deleteMutation.mutate(acc.id)}
                            disabled={deleteMutation.isPending}
                          >
                            {deleteMutation.isPending ? 'Deleting…' : 'Yes, delete account'}
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 text-xs"
                            onClick={() => setConfirming(null)}
                          >
                            Cancel
                          </Button>
                        </div>
                      </div>
                    ) : (
                      <div className="grid grid-cols-3 gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 text-xs text-muted-foreground hover:text-foreground"
                          onClick={() => setPreviewAccountId(acc.id)}
                        >
                          <Eye className="w-3 h-3 mr-1" />
                          View
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 text-xs text-amber-700 hover:bg-amber-50 hover:text-amber-800"
                          onClick={() => setConfirming({ accountId: acc.id, action: 'reset' })}
                        >
                          <RotateCcw className="w-3 h-3 mr-1" />
                          Reset
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 text-xs text-rose-700 hover:bg-rose-50 hover:text-rose-800"
                          onClick={() => setConfirming({ accountId: acc.id, action: 'delete' })}
                        >
                          <Trash2 className="w-3 h-3 mr-1" />
                          Delete
                        </Button>
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      {/* Statement preview panel */}
      {previewAccountId !== null && (
        <StatementPreviewPanel
          account={accounts?.find((a) => a.id === previewAccountId) ?? null}
          onClose={() => setPreviewAccountId(null)}
        />
      )}

      {/* Statement upload overlay */}
      {uploadingFor && (
        <div className="fixed bottom-6 right-6 z-50 bg-foreground text-background rounded-lg shadow-xl px-4 py-3 max-w-md">
          <div className="flex items-center gap-3">
            {!uploadingFor.done ? (
              <Loader2 className="w-4 h-4 animate-spin flex-shrink-0" />
            ) : uploadingFor.error ? (
              <AlertCircle className="w-4 h-4 text-amber-400 flex-shrink-0" />
            ) : (
              <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
            )}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium truncate">
                {!uploadingFor.done
                  ? `Parsing ${uploadingFor.filename}…`
                  : uploadingFor.error
                    ? 'Statement import failed'
                    : `Imported ${uploadingFor.linesAdded} line${uploadingFor.linesAdded === 1 ? '' : 's'}`}
              </p>
              <p className="text-xs opacity-70 truncate">
                {uploadingFor.error ?? uploadingFor.filename}
              </p>
            </div>
            <button
              onClick={() => setUploadingFor(null)}
              className="text-background/60 hover:text-background flex-shrink-0"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Slide-in panel */}
      {panelOpen && (
        <>
          <div className="fixed inset-0 bg-black/30 z-40" onClick={closePanel} />
          <div className="fixed right-0 top-0 h-full w-full max-w-md bg-background border-l shadow-xl z-50 flex flex-col">
            <div className="flex items-center justify-between px-5 py-4 border-b">
              <h2 className="font-semibold text-sm flex items-center gap-2">
                <Building2 className="w-4 h-4" /> New Bank Account
              </h2>
              <button onClick={closePanel} className="text-muted-foreground hover:text-foreground">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">
                  Account name <span className="text-destructive">*</span>
                </label>
                <Input
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="Business Bank Account"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Bank name</label>
                <Input
                  value={form.bank_name}
                  onChange={(e) => setForm((f) => ({ ...f, bank_name: e.target.value }))}
                  placeholder="Barclays / HSBC / ..."
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Account number</label>
                <Input
                  value={form.account_number}
                  onChange={(e) => setForm((f) => ({ ...f, account_number: e.target.value }))}
                  placeholder="090-8007-006543"
                  className="font-mono"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Currency</label>
                <NativeSelect
                  value={form.currency}
                  onChange={(e) => setForm((f) => ({ ...f, currency: e.target.value }))}
                >
                  {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
                </NativeSelect>
              </div>

              <div className="border rounded-lg p-4 space-y-3">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  Opening balances (optional)
                </p>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-muted-foreground">Statement balance</label>
                    <Input
                      type="number" step="0.01"
                      value={form.statement_balance}
                      onChange={(e) => setForm((f) => ({ ...f, statement_balance: parseFloat(e.target.value) || 0 }))}
                      className="font-mono text-right"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-muted-foreground">OOO balance</label>
                    <Input
                      type="number" step="0.01"
                      value={form.ooo_balance}
                      onChange={(e) => setForm((f) => ({ ...f, ooo_balance: parseFloat(e.target.value) || 0 }))}
                      className="font-mono text-right"
                    />
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">
                  These get updated automatically when you import statements and reconcile.
                </p>
              </div>
            </div>

            <div className="px-5 py-4 border-t flex items-center gap-3">
              <Button
                className="flex-1"
                onClick={() => createMutation.mutate()}
                disabled={!canSave || createMutation.isPending}
              >
                {createMutation.isPending ? 'Saving…' : 'Add Account'}
              </Button>
              <Button variant="outline" onClick={closePanel}>
                Cancel
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Statement preview — shows all imported lines for one account with their
// reconciliation status. Read-only; users go to /reconciliation to act on them.
// ─────────────────────────────────────────────────────────────────────────────

const LINE_STATUS_VARIANT: Record<string, 'success' | 'warning' | 'info' | 'muted'> = {
  pending: 'warning',
  matched: 'success',
  manual: 'info',
  transfer: 'info',
  discussed: 'muted',
}

const LINE_STATUS_LABEL: Record<string, string> = {
  pending: 'Pending',
  matched: 'Reconciled',
  manual: 'Manual entry',
  transfer: 'Transfer',
  discussed: 'In discussion',
}

function StatementPreviewPanel({
  account, onClose,
}: {
  account: BankAccount | null
  onClose: () => void
}) {
  const navigate = useNavigate()
  const { data: lines, isLoading } = useQuery<StatementLine[]>({
    queryKey: ['statement-lines', account?.id, 'all'],
    queryFn: () =>
      api.get('/statement-lines/', { params: { bank_account_id: account?.id } }).then((r) => r.data),
    enabled: account !== null,
  })

  if (!account) return null

  const counts = {
    total: lines?.length ?? 0,
    pending: lines?.filter((l) => l.status === 'pending').length ?? 0,
    reconciled: lines?.filter((l) => l.status === 'matched' || l.status === 'manual' || l.status === 'transfer').length ?? 0,
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      <div className="fixed right-0 top-0 h-full w-full max-w-2xl bg-background border-l shadow-xl z-50 flex flex-col">
        {/* Header */}
        <div className="px-5 py-4 border-b flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="font-semibold">{account.name}</h2>
            <p className="text-xs text-muted-foreground font-mono mt-0.5">
              {account.bank_name && `${account.bank_name} · `}
              {account.account_number ?? ''}
            </p>
            <div className="flex items-center gap-4 mt-2 text-xs">
              <span className="text-muted-foreground">
                {counts.total} transaction{counts.total === 1 ? '' : 's'}
              </span>
              {counts.pending > 0 && (
                <span className="text-amber-700">
                  ● {counts.pending} pending
                </span>
              )}
              {counts.reconciled > 0 && (
                <span className="text-emerald-700">
                  ● {counts.reconciled} reconciled
                </span>
              )}
            </div>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground flex-shrink-0">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="p-4 space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : !lines?.length ? (
            <div className="py-12 text-center text-sm text-muted-foreground">
              No transactions yet. Use “Import statement” to load a CSV or PDF.
            </div>
          ) : (
            <div>
              {lines.map((l) => {
                const isInflow = l.received > 0
                const amount = isInflow ? l.received : l.spent
                return (
                  <div
                    key={l.id}
                    className="flex items-center justify-between gap-3 px-5 py-2.5 border-b last:border-0 hover:bg-muted/30 transition-colors"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-sm truncate">{l.description}</p>
                      <div className="flex items-center gap-2 mt-0.5">
                        <p className="text-[11px] text-muted-foreground">{formatDate(l.date)}</p>
                        {l.reference && (
                          <p className="text-[11px] text-muted-foreground font-mono truncate">
                            · {l.reference}
                          </p>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-3 flex-shrink-0">
                      <p
                        className={cn(
                          'text-sm font-mono font-medium',
                          isInflow ? 'text-emerald-700' : 'text-rose-700',
                        )}
                      >
                        {isInflow ? '+' : '−'}{formatCurrency(amount, account.currency)}
                      </p>
                      <Badge variant={LINE_STATUS_VARIANT[l.status] ?? 'muted'}>
                        {LINE_STATUS_LABEL[l.status] ?? l.status}
                      </Badge>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        {counts.pending > 0 && (
          <div className="px-5 py-3 border-t">
            <Button
              size="sm"
              className="w-full"
              onClick={() => {
                onClose()
                navigate(`/reconciliation?account=${account.id}`)
              }}
            >
              Reconcile {counts.pending} pending
              <ArrowRight className="w-3.5 h-3.5 ml-1.5" />
            </Button>
          </div>
        )}
      </div>
    </>
  )
}
