import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, X, Receipt, Upload, Loader2, AlertCircle } from 'lucide-react'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { cn, formatCurrency, formatDate } from '@/lib/utils'
import type { DocumentStatus, Invoice, InvoiceLineCreate } from '@/types'

type Tab = 'all' | DocumentStatus

const STATUS_VARIANT: Record<DocumentStatus, 'success' | 'warning' | 'info' | 'muted' | 'destructive'> = {
  draft: 'muted',
  awaiting_approval: 'info',
  awaiting_payment: 'warning',
  paid: 'success',
  voided: 'destructive',
}

const STATUS_LABEL: Record<DocumentStatus, string> = {
  draft: 'Draft',
  awaiting_approval: 'Awaiting Approval',
  awaiting_payment: 'Awaiting Payment',
  paid: 'Paid',
  voided: 'Voided',
}

const TABS: { id: Tab; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'draft', label: 'Draft' },
  { id: 'awaiting_approval', label: 'Awaiting Approval' },
  { id: 'awaiting_payment', label: 'Awaiting Payment' },
  { id: 'paid', label: 'Paid' },
]

const todayISO = () => new Date().toISOString().slice(0, 10)

const newLine = (): InvoiceLineCreate => ({
  description: '',
  quantity: 1,
  unit_price: 0,
  tax_rate: 0,
})

type UploadState = {
  current: number
  total: number
  filename: string
  errors: { filename: string; message: string }[]
} | null

export default function Sales() {
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<Tab>('all')
  const [panelOpen, setPanelOpen] = useState(false)
  const [viewing, setViewing] = useState<Invoice | null>(null)
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [uploading, setUploading] = useState<UploadState>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Create form state
  const [form, setForm] = useState({
    number: '',
    contact_name: '',
    reference: '',
    issue_date: todayISO(),
    due_date: '',
    notes: '',
    status: 'draft' as DocumentStatus,
  })
  const [lines, setLines] = useState<InvoiceLineCreate[]>([newLine()])

  const { data: invoices, isLoading } = useQuery<Invoice[]>({
    queryKey: ['invoices'],
    queryFn: () => api.get('/invoices/').then((r) => r.data),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      api.post('/invoices/', {
        ...form,
        reference: form.reference || null,
        due_date: form.due_date || null,
        notes: form.notes || null,
        lines: lines.filter((l) => l.description.trim()),
      }),
    onSuccess: () => {
      closePanel()
      queryClient.invalidateQueries({ queryKey: ['invoices'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/invoices/${id}`),
    onSuccess: () => {
      setDeleteId(null)
      queryClient.invalidateQueries({ queryKey: ['invoices'] })
    },
  })

  const uploadOne = async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    await api.post('/invoices/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  }

  const handleFiles = async (filesList: FileList | null) => {
    if (!filesList || filesList.length === 0) return
    const files = Array.from(filesList)
    const errors: { filename: string; message: string }[] = []

    setUploading({ current: 0, total: files.length, filename: files[0].name, errors: [] })
    for (let i = 0; i < files.length; i++) {
      const f = files[i]
      setUploading((prev) =>
        prev ? { ...prev, current: i + 1, filename: f.name } : prev,
      )
      try {
        await uploadOne(f)
        queryClient.invalidateQueries({ queryKey: ['invoices'] })
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        errors.push({ filename: f.name, message: msg })
      }
    }
    setUploading((prev) => (prev ? { ...prev, errors } : prev))
    // Auto-dismiss after a short delay if there are no errors
    if (errors.length === 0) {
      setTimeout(() => setUploading(null), 1500)
    }
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const counts: Record<Tab, number> = {
    all: invoices?.length ?? 0,
    draft: invoices?.filter((i) => i.status === 'draft').length ?? 0,
    awaiting_approval: invoices?.filter((i) => i.status === 'awaiting_approval').length ?? 0,
    awaiting_payment: invoices?.filter((i) => i.status === 'awaiting_payment').length ?? 0,
    paid: invoices?.filter((i) => i.status === 'paid').length ?? 0,
    voided: invoices?.filter((i) => i.status === 'voided').length ?? 0,
  }

  const filtered = (invoices ?? []).filter((i) => tab === 'all' || i.status === tab)
  const totalOutstanding = filtered.reduce((sum, i) => sum + (i.outstanding ?? 0), 0)

  // Live totals on the form
  const subtotal = lines.reduce((s, l) => s + l.quantity * l.unit_price, 0)
  const taxTotal = lines.reduce((s, l) => s + l.quantity * l.unit_price * l.tax_rate, 0)
  const total = subtotal + taxTotal

  const updateLine = <K extends keyof InvoiceLineCreate>(
    i: number, field: K, value: InvoiceLineCreate[K],
  ) => setLines((prev) => prev.map((l, idx) => (idx === i ? { ...l, [field]: value } : l)))

  const addLine = () => setLines((prev) => [...prev, newLine()])
  const removeLine = (i: number) =>
    setLines((prev) => (prev.length === 1 ? prev : prev.filter((_, idx) => idx !== i)))

  const openCreate = () => {
    setForm({
      number: `INV-${String((invoices?.length ?? 0) + 1).padStart(4, '0')}`,
      contact_name: '',
      reference: '',
      issue_date: todayISO(),
      due_date: '',
      notes: '',
      status: 'draft',
    })
    setLines([newLine()])
    setViewing(null)
    setPanelOpen(true)
  }

  const openView = (inv: Invoice) => {
    setViewing(inv)
    setPanelOpen(true)
  }

  const closePanel = () => {
    setPanelOpen(false)
    setViewing(null)
  }

  const canSave =
    form.number.trim() && form.contact_name.trim() && lines.some((l) => l.description.trim())

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold">Sales</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Invoices issued to customers — money owed to you.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".pdf,.png,.jpg,.jpeg,.webp,application/pdf,image/*"
            className="hidden"
            onChange={(e) => handleFiles(e.target.files)}
          />
          <Button
            size="sm"
            variant="outline"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading !== null}
          >
            <Upload className="w-3.5 h-3.5 mr-1.5" />
            Import PDF
          </Button>
          <Button size="sm" onClick={openCreate}>
            <Plus className="w-3.5 h-3.5 mr-1.5" />
            New Invoice
          </Button>
        </div>
      </div>

      {/* Status tabs */}
      <div className="flex items-center border-b">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              'px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors flex items-center gap-2',
              tab === t.id
                ? 'border-primary text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            {t.label}
            {counts[t.id] > 0 && (
              <span
                className={cn(
                  'text-xs px-1.5 py-0.5 rounded-full font-mono',
                  tab === t.id ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground',
                )}
              >
                {counts[t.id]}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Outstanding summary */}
      {filtered.length > 0 && (
        <div className="flex justify-end text-xs text-muted-foreground">
          {filtered.length} items · Total outstanding: {' '}
          <span className="font-semibold text-foreground ml-1">
            {formatCurrency(totalOutstanding)}
          </span>
        </div>
      )}

      {/* Table */}
      <Card>
        <CardContent className="p-0 overflow-x-auto">
          {isLoading ? (
            <div className="p-4 space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : !filtered.length ? (
            <div className="py-16 text-center">
              <Receipt className="w-8 h-8 text-muted-foreground mx-auto mb-3 opacity-40" />
              <p className="text-sm text-muted-foreground">
                {tab === 'all' ? (
                  <>
                    No invoices yet.{' '}
                    <button onClick={openCreate} className="text-primary hover:underline">
                      Create your first invoice.
                    </button>
                  </>
                ) : (
                  <>No invoices with status “{STATUS_LABEL[tab as DocumentStatus]}”.</>
                )}
              </p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/40">
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">Number</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">Customer</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">Ref</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">Date</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">Due</th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold text-muted-foreground">Total</th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold text-muted-foreground">Outstanding</th>
                  <th className="px-4 py-2.5 text-center text-xs font-semibold text-muted-foreground">Status</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {filtered.map((inv) => (
                  <tr
                    key={inv.id}
                    className="border-b last:border-0 hover:bg-muted/30 cursor-pointer transition-colors"
                    onClick={() => openView(inv)}
                  >
                    <td className="px-4 py-2.5 font-mono text-xs font-medium">{inv.number}</td>
                    <td className="px-4 py-2.5">{inv.contact_name}</td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground">{inv.reference ?? '—'}</td>
                    <td className="px-4 py-2.5 text-xs whitespace-nowrap">{formatDate(inv.issue_date)}</td>
                    <td className="px-4 py-2.5 text-xs whitespace-nowrap">
                      {inv.due_date ? formatDate(inv.due_date) : '—'}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-sm">
                      {formatCurrency(inv.total, inv.currency)}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-sm">
                      {inv.outstanding > 0 ? (
                        <span className="text-amber-700 font-medium">
                          {formatCurrency(inv.outstanding, inv.currency)}
                        </span>
                      ) : (
                        <span className="text-emerald-700">{formatCurrency(0, inv.currency)}</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      <Badge variant={STATUS_VARIANT[inv.status]}>{STATUS_LABEL[inv.status]}</Badge>
                    </td>
                    <td className="px-4 py-2.5 text-right" onClick={(e) => e.stopPropagation()}>
                      {deleteId === inv.id ? (
                        <div className="inline-flex items-center gap-1.5">
                          <span className="text-xs text-muted-foreground">Delete?</span>
                          <Button
                            size="sm" variant="destructive" className="h-6 px-2 text-xs"
                            onClick={() => deleteMutation.mutate(inv.id)}
                            disabled={deleteMutation.isPending}
                          >Yes</Button>
                          <Button
                            size="sm" variant="outline" className="h-6 px-2 text-xs"
                            onClick={() => setDeleteId(null)}
                          >No</Button>
                        </div>
                      ) : (
                        <Button
                          size="sm" variant="ghost"
                          className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                          onClick={() => setDeleteId(inv.id)}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {/* Upload progress overlay */}
      {uploading && (
        <div className="fixed bottom-6 right-6 z-50 bg-foreground text-background rounded-lg shadow-xl px-4 py-3 max-w-md">
          <div className="flex items-center gap-3">
            {uploading.current < uploading.total ? (
              <Loader2 className="w-4 h-4 animate-spin flex-shrink-0" />
            ) : uploading.errors.length === 0 ? (
              <Receipt className="w-4 h-4 text-emerald-400 flex-shrink-0" />
            ) : (
              <AlertCircle className="w-4 h-4 text-amber-400 flex-shrink-0" />
            )}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium truncate">
                {uploading.current < uploading.total
                  ? `Importing ${uploading.filename}…`
                  : uploading.errors.length === 0
                    ? `Imported ${uploading.total} file${uploading.total === 1 ? '' : 's'}`
                    : `Done — ${uploading.errors.length} of ${uploading.total} failed`}
              </p>
              <p className="text-xs opacity-70">
                {uploading.current} of {uploading.total}
              </p>
            </div>
            <button
              onClick={() => setUploading(null)}
              className="text-background/60 hover:text-background flex-shrink-0"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
          {uploading.errors.length > 0 && uploading.current >= uploading.total && (
            <div className="mt-2 pt-2 border-t border-background/20 space-y-1">
              {uploading.errors.map((e, i) => (
                <p key={i} className="text-xs opacity-80">
                  <span className="font-mono">{e.filename}</span>: {e.message}
                </p>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Slide-in panel */}
      {panelOpen && (
        <>
          <div className="fixed inset-0 bg-black/30 z-40" onClick={closePanel} />
          <div className="fixed right-0 top-0 h-full w-full max-w-2xl bg-background border-l shadow-xl z-50 flex flex-col">
            {/* Panel header */}
            <div className="flex items-center justify-between px-5 py-4 border-b">
              <div>
                <h2 className="font-semibold">
                  {viewing ? `Invoice ${viewing.number}` : 'New Invoice'}
                </h2>
                {viewing && (
                  <Badge variant={STATUS_VARIANT[viewing.status]} className="mt-1">
                    {STATUS_LABEL[viewing.status]}
                  </Badge>
                )}
              </div>
              <button onClick={closePanel} className="text-muted-foreground hover:text-foreground">
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
              {viewing ? (
                <>
                  {/* View mode */}
                  <div className="grid grid-cols-2 gap-4">
                    <Field label="Customer" value={viewing.contact_name} />
                    <Field label="Reference" value={viewing.reference ?? '—'} />
                    <Field label="Issue date" value={formatDate(viewing.issue_date)} />
                    <Field label="Due date" value={viewing.due_date ? formatDate(viewing.due_date) : '—'} />
                  </div>

                  <div>
                    <p className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wide">
                      Line items
                    </p>
                    <table className="w-full text-sm border rounded-lg overflow-hidden">
                      <thead>
                        <tr className="bg-muted/40">
                          <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">Description</th>
                          <th className="px-3 py-2 text-right text-xs font-semibold text-muted-foreground">Qty</th>
                          <th className="px-3 py-2 text-right text-xs font-semibold text-muted-foreground">Unit</th>
                          <th className="px-3 py-2 text-right text-xs font-semibold text-muted-foreground">VAT</th>
                          <th className="px-3 py-2 text-right text-xs font-semibold text-muted-foreground">Total</th>
                        </tr>
                      </thead>
                      <tbody>
                        {viewing.lines.map((l) => (
                          <tr key={l.id} className="border-t">
                            <td className="px-3 py-2">{l.description}</td>
                            <td className="px-3 py-2 text-right font-mono">{l.quantity}</td>
                            <td className="px-3 py-2 text-right font-mono">{l.unit_price.toFixed(2)}</td>
                            <td className="px-3 py-2 text-right font-mono">{(l.tax_rate * 100).toFixed(0)}%</td>
                            <td className="px-3 py-2 text-right font-mono">{l.line_total.toFixed(2)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <Totals
                    subtotal={viewing.subtotal}
                    tax={viewing.tax_total}
                    total={viewing.total}
                    paid={viewing.paid_amount}
                    outstanding={viewing.outstanding}
                    currency={viewing.currency}
                  />

                  {viewing.notes && (
                    <Field label="Notes" value={viewing.notes} />
                  )}
                </>
              ) : (
                <>
                  {/* Create mode */}
                  <div className="grid grid-cols-2 gap-4">
                    <FormRow label="Invoice number" required>
                      <Input value={form.number} onChange={(e) => setForm((f) => ({ ...f, number: e.target.value }))} />
                    </FormRow>
                    <FormRow label="Customer" required>
                      <Input
                        value={form.contact_name}
                        onChange={(e) => setForm((f) => ({ ...f, contact_name: e.target.value }))}
                        placeholder="Customer name"
                      />
                    </FormRow>
                    <FormRow label="Reference">
                      <Input
                        value={form.reference}
                        onChange={(e) => setForm((f) => ({ ...f, reference: e.target.value }))}
                        placeholder="PO number / external ref"
                      />
                    </FormRow>
                    <FormRow label="Issue date" required>
                      <Input
                        type="date"
                        value={form.issue_date}
                        onChange={(e) => setForm((f) => ({ ...f, issue_date: e.target.value }))}
                      />
                    </FormRow>
                    <FormRow label="Due date">
                      <Input
                        type="date"
                        value={form.due_date}
                        onChange={(e) => setForm((f) => ({ ...f, due_date: e.target.value }))}
                      />
                    </FormRow>
                  </div>

                  {/* Lines */}
                  <div>
                    <p className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wide">
                      Line items
                    </p>
                    <div className="space-y-2">
                      <div className="grid grid-cols-[1fr_60px_90px_70px_90px_24px] gap-2 text-xs font-medium text-muted-foreground px-1">
                        <span>Description</span>
                        <span className="text-right">Qty</span>
                        <span className="text-right">Unit</span>
                        <span className="text-right">VAT %</span>
                        <span className="text-right">Line</span>
                        <span />
                      </div>
                      {lines.map((line, i) => (
                        <div
                          key={i}
                          className="grid grid-cols-[1fr_60px_90px_70px_90px_24px] gap-2 items-center"
                        >
                          <Input
                            value={line.description}
                            onChange={(e) => updateLine(i, 'description', e.target.value)}
                            placeholder="Item description"
                          />
                          <Input
                            type="number" min="0" step="0.01"
                            value={line.quantity}
                            onChange={(e) => updateLine(i, 'quantity', parseFloat(e.target.value) || 0)}
                            className="text-right font-mono"
                          />
                          <Input
                            type="number" min="0" step="0.01"
                            value={line.unit_price}
                            onChange={(e) => updateLine(i, 'unit_price', parseFloat(e.target.value) || 0)}
                            className="text-right font-mono"
                          />
                          <Input
                            type="number" min="0" max="100" step="1"
                            value={line.tax_rate * 100}
                            onChange={(e) => updateLine(i, 'tax_rate', (parseFloat(e.target.value) || 0) / 100)}
                            className="text-right font-mono"
                          />
                          <span className="text-right font-mono text-sm pr-2">
                            {(line.quantity * line.unit_price).toFixed(2)}
                          </span>
                          <button
                            onClick={() => removeLine(i)}
                            disabled={lines.length === 1}
                            className="text-muted-foreground hover:text-destructive disabled:opacity-30"
                          >
                            <X className="w-4 h-4" />
                          </button>
                        </div>
                      ))}
                      <Button variant="ghost" size="sm" onClick={addLine}>
                        <Plus className="w-3.5 h-3.5 mr-1" />
                        Add line
                      </Button>
                    </div>
                  </div>

                  <Totals subtotal={subtotal} tax={taxTotal} total={total} />

                  <FormRow label="Notes">
                    <Textarea
                      value={form.notes}
                      onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
                      placeholder="Notes shown on the invoice…"
                    />
                  </FormRow>
                </>
              )}
            </div>

            {/* Footer */}
            {!viewing && (
              <div className="px-5 py-4 border-t flex items-center gap-3">
                <Button
                  className="flex-1"
                  onClick={() => createMutation.mutate()}
                  disabled={!canSave || createMutation.isPending}
                >
                  {createMutation.isPending ? 'Saving…' : 'Save as Draft'}
                </Button>
                <Button
                  variant="default"
                  className="flex-1"
                  onClick={() => {
                    setForm((f) => ({ ...f, status: 'awaiting_payment' }))
                    setTimeout(() => createMutation.mutate(), 0)
                  }}
                  disabled={!canSave || createMutation.isPending}
                >
                  Approve
                </Button>
                <Button variant="outline" onClick={closePanel}>
                  Cancel
                </Button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

// ── Small presentational helpers ─────────────────────────────────────────────

function FormRow({
  label, required, children,
}: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-medium text-muted-foreground">
        {label} {required && <span className="text-destructive">*</span>}
      </label>
      {children}
    </div>
  )
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground mb-1">{label}</p>
      <p className="text-sm">{value}</p>
    </div>
  )
}

function Totals({
  subtotal, tax, total, paid, outstanding, currency = 'GBP',
}: {
  subtotal: number; tax: number; total: number
  paid?: number; outstanding?: number; currency?: string
}) {
  return (
    <div className="flex justify-end">
      <div className="w-64 space-y-1 text-sm">
        <div className="flex justify-between">
          <span className="text-muted-foreground">Subtotal</span>
          <span className="font-mono">{formatCurrency(subtotal, currency)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">VAT</span>
          <span className="font-mono">{formatCurrency(tax, currency)}</span>
        </div>
        <div className="flex justify-between font-bold border-t pt-1.5 mt-1.5">
          <span>Total</span>
          <span className="font-mono">{formatCurrency(total, currency)}</span>
        </div>
        {paid !== undefined && (
          <div className="flex justify-between text-emerald-700 pt-1">
            <span>Paid</span>
            <span className="font-mono">{formatCurrency(paid, currency)}</span>
          </div>
        )}
        {outstanding !== undefined && outstanding > 0 && (
          <div className="flex justify-between text-amber-700 font-semibold">
            <span>Outstanding</span>
            <span className="font-mono">{formatCurrency(outstanding, currency)}</span>
          </div>
        )}
      </div>
    </div>
  )
}
