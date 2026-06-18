import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, X, Receipt, Upload, Pencil, Check, Loader2 } from 'lucide-react'
import { UploadDock, type UploadItem } from '@/components/UploadDock'
import { humanizeUploadError } from '@/lib/upload-errors'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { useConfirm } from '@/components/ConfirmProvider'
import { cn, formatCurrency, formatDate } from '@/lib/utils'
import { CreditsList } from '@/components/CreditsList'
import type { DocumentStatus, Invoice, InvoiceLineCreate, Credit } from '@/types'

type Tab = 'all' | DocumentStatus | 'credits'

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
  { id: 'credits', label: 'Overpayments & Prepayments' },
]

const todayISO = () => new Date().toISOString().slice(0, 10)

const newLine = (): InvoiceLineCreate => ({
  description: '',
  quantity: 1,
  unit_price: 0,
  tax_rate: 0,
})

export default function Sales() {
  const queryClient = useQueryClient()
  const confirm = useConfirm()
  const [tab, setTab] = useState<Tab>('all')
  const [panelOpen, setPanelOpen] = useState(false)
  const [viewing, setViewing] = useState<Invoice | null>(null)
  const [editing, setEditing] = useState(false)
  const [editForm, setEditForm] = useState<{
    number: string; contact_name: string; issue_date: string
    due_date: string; total: string; currency: string; status: DocumentStatus; notes: string
  } | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [uploadItems, setUploadItems] = useState<UploadItem[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)

  const isUploading = uploadItems.some((i) => i.status === 'queued' || i.status === 'uploading')

  const patchItem = (id: string, updates: Partial<UploadItem>) =>
    setUploadItems((prev) => prev.map((it) => (it.id === id ? { ...it, ...updates } : it)))

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

  const { data: receivableCredits } = useQuery<Credit[]>({
    queryKey: ['credits', 'receivable'],
    queryFn: () => api.get('/credits/?direction=receivable').then((r) => r.data),
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
      setDeletingId(null)
      queryClient.invalidateQueries({ queryKey: ['invoices'] })
    },
    onError: () => setDeletingId(null),
  })

  const askDelete = async (inv: Invoice) => {
    const ok = await confirm({
      title: 'Delete this invoice?',
      description: 'This permanently removes the invoice.',
      confirmText: 'Delete',
      destructive: true,
      rememberKey: 'delete-invoice',
    })
    if (ok) {
      setDeletingId(inv.id)
      deleteMutation.mutate(inv.id)
    }
  }

  const editMutation = useMutation({
    mutationFn: (payload: object) =>
      api.patch(`/invoices/${viewing!.id}`, payload).then((r) => r.data as Invoice),
    onSuccess: (updated) => {
      setViewing(updated)
      setEditing(false)
      queryClient.invalidateQueries({ queryKey: ['invoices'] })
    },
  })

  const startEdit = () => {
    if (!viewing) return
    setEditForm({
      number: viewing.number ?? '',
      contact_name: viewing.contact_name,
      issue_date: viewing.issue_date,
      due_date: viewing.due_date ?? '',
      total: String(viewing.total),
      currency: viewing.currency,
      status: viewing.status,
      notes: viewing.notes ?? '',
    })
    setEditing(true)
  }

  const saveEdit = () => {
    if (!editForm) return
    editMutation.mutate({
      number: editForm.number || undefined,
      contact_name: editForm.contact_name || undefined,
      issue_date: editForm.issue_date || undefined,
      due_date: editForm.due_date || undefined,
      total: parseFloat(editForm.total) || undefined,
      currency: editForm.currency || undefined,
      status: editForm.status || undefined,
      notes: editForm.notes || undefined,
    })
  }

  const uploadOne = async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    const isCsv = file.name.toLowerCase().endsWith('.csv') || file.type === 'text/csv'
    await api.post(isCsv ? '/invoices/upload-csv' : '/invoices/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  }

  const runUpload = async (item: UploadItem) => {
    patchItem(item.id, { status: 'uploading', error: undefined })
    try {
      await uploadOne(item.file)
      patchItem(item.id, { status: 'done' })
      queryClient.invalidateQueries({ queryKey: ['invoices'] })
    } catch (err) {
      const raw = err instanceof Error ? err.message : String(err)
      patchItem(item.id, { status: 'failed', error: humanizeUploadError(raw) })
    }
  }

  const handleFiles = async (filesList: FileList | null) => {
    if (!filesList || filesList.length === 0) return
    const files = Array.from(filesList)

    const newItems: UploadItem[] = files.map((f) => ({
      id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      file: f,
      filename: f.name,
      status: 'queued',
      retryCount: 0,
    }))
    setUploadItems((prev) => [...prev, ...newItems])

    // Concurrency 2 — Gemini free tier rate-limits at ~15 RPM. Two in parallel
    // gives a good balance of speed vs rate-limit hits. The backend also
    // retries transient errors with backoff, so an occasional hit just slows
    // things down rather than failing the file.
    const CONCURRENCY = 2
    for (let i = 0; i < newItems.length; i += CONCURRENCY) {
      const batch = newItems.slice(i, i + CONCURRENCY)
      await Promise.all(batch.map(runUpload))
    }

    // Auto-clear successful uploads if nothing failed in the whole dock
    setTimeout(() => {
      setUploadItems((prev) =>
        prev.some((it) => it.status === 'failed')
          ? prev
          : prev.filter((it) => it.status !== 'done'),
      )
    }, 3000)

    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const retryItem = async (item: UploadItem) => {
    const next: UploadItem = { ...item, retryCount: item.retryCount + 1 }
    patchItem(next.id, { retryCount: next.retryCount })
    await runUpload(next)
    // Auto-clear if it succeeded and no failures remain
    setTimeout(() => {
      setUploadItems((prev) =>
        prev.some((it) => it.status === 'failed')
          ? prev
          : prev.filter((it) => it.status !== 'done'),
      )
    }, 2000)
  }

  const retryAllFailed = () => {
    uploadItems.filter((i) => i.status === 'failed').forEach(retryItem)
  }

  const dismissItem = (id: string) =>
    setUploadItems((prev) => prev.filter((i) => i.id !== id))
  const dismissAll = () => setUploadItems([])

  const counts: Record<Tab, number> = {
    all: invoices?.length ?? 0,
    draft: invoices?.filter((i) => i.status === 'draft').length ?? 0,
    awaiting_approval: invoices?.filter((i) => i.status === 'awaiting_approval').length ?? 0,
    awaiting_payment: invoices?.filter((i) => i.status === 'awaiting_payment').length ?? 0,
    paid: invoices?.filter((i) => i.status === 'paid').length ?? 0,
    voided: invoices?.filter((i) => i.status === 'voided').length ?? 0,
    credits: receivableCredits?.filter((c) => c.outstanding > 0.005).length ?? 0,
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
    setEditing(false)
    setEditForm(null)
    setPanelOpen(true)
  }

  const closePanel = () => {
    setPanelOpen(false)
    setViewing(null)
    setEditing(false)
    setEditForm(null)
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
            accept=".pdf,.png,.jpg,.jpeg,.webp,.csv,application/pdf,image/*,text/csv"
            className="hidden"
            onChange={(e) => handleFiles(e.target.files)}
          />
          <Button
            size="sm"
            variant="outline"
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading}
          >
            <Upload className="w-3.5 h-3.5 mr-1.5" />
            Import PDF / CSV
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

      {tab === 'credits' ? (
        <CreditsList direction="receivable" />
      ) : (
      <>
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
                      <Button
                        size="sm" variant="ghost"
                        className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                        onClick={() => askDelete(inv)}
                        disabled={deletingId === inv.id}
                      >
                        {deletingId === inv.id
                          ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          : <Trash2 className="w-3.5 h-3.5" />}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
      </>
      )}

      {/* Upload dock — visible whenever there are items, persistent for failures */}
      <UploadDock
        items={uploadItems}
        onRetry={retryItem}
        onRetryAll={retryAllFailed}
        onDismiss={dismissItem}
        onDismissAll={dismissAll}
      />

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
                {viewing && !editing && (
                  <Badge variant={STATUS_VARIANT[viewing.status]} className="mt-1">
                    {STATUS_LABEL[viewing.status]}
                  </Badge>
                )}
              </div>
              <div className="flex items-center gap-1">
                {viewing && !editing && (
                  <Button size="sm" variant="outline" onClick={startEdit} className="h-7 px-2 text-xs">
                    <Pencil className="w-3 h-3 mr-1" /> Edit
                  </Button>
                )}
                <button onClick={closePanel} className="text-muted-foreground hover:text-foreground p-1">
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
              {viewing ? (
                editing && editForm ? (
                  <>
                    {/* Edit mode */}
                    <div className="grid grid-cols-2 gap-4">
                      <FormRow label="Invoice number">
                        <Input value={editForm.number} onChange={(e) => setEditForm((f) => f && ({ ...f, number: e.target.value }))} />
                      </FormRow>
                      <FormRow label="Customer" required>
                        <Input value={editForm.contact_name} onChange={(e) => setEditForm((f) => f && ({ ...f, contact_name: e.target.value }))} />
                      </FormRow>
                      <FormRow label="Issue date">
                        <Input type="date" value={editForm.issue_date} onChange={(e) => setEditForm((f) => f && ({ ...f, issue_date: e.target.value }))} />
                      </FormRow>
                      <FormRow label="Due date">
                        <Input type="date" value={editForm.due_date} onChange={(e) => setEditForm((f) => f && ({ ...f, due_date: e.target.value }))} />
                      </FormRow>
                      <FormRow label="Total amount">
                        <Input type="number" min="0" step="0.01" value={editForm.total}
                          onChange={(e) => setEditForm((f) => f && ({ ...f, total: e.target.value }))} className="font-mono" />
                      </FormRow>
                      <FormRow label="Currency">
                        <Input value={editForm.currency} maxLength={3} onChange={(e) => setEditForm((f) => f && ({ ...f, currency: e.target.value.toUpperCase() }))} className="font-mono uppercase" />
                      </FormRow>
                      <FormRow label="Status">
                        <select
                          value={editForm.status}
                          onChange={(e) => setEditForm((f) => f && ({ ...f, status: e.target.value as DocumentStatus }))}
                          className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm"
                        >
                          <option value="draft">Draft</option>
                          <option value="awaiting_approval">Awaiting Approval</option>
                          <option value="awaiting_payment">Awaiting Payment</option>
                          <option value="paid">Paid</option>
                          <option value="voided">Voided</option>
                        </select>
                      </FormRow>
                    </div>
                    <FormRow label="Notes">
                      <Textarea value={editForm.notes} onChange={(e) => setEditForm((f) => f && ({ ...f, notes: e.target.value }))} placeholder="Notes…" />
                    </FormRow>
                  </>
                ) : (
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
                )
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
            {viewing && editing && (
              <div className="px-5 py-4 border-t flex items-center gap-3">
                <Button
                  className="flex-1"
                  onClick={saveEdit}
                  disabled={editMutation.isPending}
                >
                  <Check className="w-3.5 h-3.5 mr-1.5" />
                  {editMutation.isPending ? 'Saving…' : 'Save changes'}
                </Button>
                <Button variant="outline" onClick={() => { setEditing(false); setEditForm(null) }}>
                  Cancel
                </Button>
              </div>
            )}
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
