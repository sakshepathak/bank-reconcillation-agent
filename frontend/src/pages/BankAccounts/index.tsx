import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  Plus, X, Landmark, Upload, Loader2, AlertCircle,
  ArrowRight, Check, Building2,
} from 'lucide-react'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { cn, formatCurrency, formatDate } from '@/lib/utils'
import type { BankAccount } from '@/types'

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
  const [uploadingFor, setUploadingFor] = useState<UploadState>(null)
  const fileRefs = useRef<Record<number, HTMLInputElement | null>>({})

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

  const canSave = form.name.trim().length > 0

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold">Bank Accounts</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Statement balance (what the bank says) vs OOO balance (what we tracked).
            The gap is what reconciliation closes.
          </p>
        </div>
        <Button size="sm" onClick={openCreate}>
          <Plus className="w-3.5 h-3.5 mr-1.5" />
          New Account
        </Button>
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
            <p className="text-sm text-muted-foreground">
              No bank accounts yet.{' '}
              <button onClick={openCreate} className="text-primary hover:underline">
                Add your first account.
              </button>
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {accounts.map((acc) => {
            const reconciled = Math.abs(acc.balance_difference) < 0.01
            return (
              <Card key={acc.id} className="overflow-hidden">
                <CardContent className="p-5">
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
                      <p className="text-xl font-bold font-mono">
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
                      <p className="text-xl font-bold font-mono">
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
                </CardContent>
              </Card>
            )
          })}
        </div>
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
