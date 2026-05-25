import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Pencil, Trash2, X, Check } from 'lucide-react'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { NativeSelect } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import type { Contact, ContactType } from '@/types'

const TYPE_VARIANT: Record<ContactType, 'info' | 'success' | 'muted' | 'warning'> = {
  customer: 'info',
  supplier: 'success',
  internal: 'muted',
  other: 'warning',
}

const TYPE_TABS: { label: string; value: ContactType | 'all' }[] = [
  { label: 'All', value: 'all' },
  { label: 'Customers', value: 'customer' },
  { label: 'Suppliers', value: 'supplier' },
  { label: 'Internal', value: 'internal' },
  { label: 'Other', value: 'other' },
]

type PanelMode = 'create' | 'edit'

interface FormState {
  full_name: string
  company: string
  contact_type: ContactType
  email: string
  phone: string
  address: string
  notes: string
}

const EMPTY_FORM: FormState = {
  full_name: '',
  company: '',
  contact_type: 'customer',
  email: '',
  phone: '',
  address: '',
  notes: '',
}

function contactToForm(c: Contact): FormState {
  return {
    full_name: c.full_name,
    company: c.company ?? '',
    contact_type: c.contact_type as ContactType,
    email: c.email ?? '',
    phone: c.phone ?? '',
    address: c.address ?? '',
    notes: c.notes ?? '',
  }
}

export default function Contacts() {
  const queryClient = useQueryClient()
  const [typeFilter, setTypeFilter] = useState<ContactType | 'all'>('all')
  const [panel, setPanel] = useState<{ open: boolean; mode: PanelMode; id?: number }>({
    open: false,
    mode: 'create',
  })
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [deleteId, setDeleteId] = useState<number | null>(null)

  const { data: contacts, isLoading } = useQuery<Contact[]>({
    queryKey: ['contacts', typeFilter],
    queryFn: () =>
      api
        .get('/contacts/', { params: typeFilter !== 'all' ? { contact_type: typeFilter } : {} })
        .then((r) => r.data),
  })

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['contacts'] })

  const createMutation = useMutation({
    mutationFn: (data: FormState) =>
      api.post('/contacts/', {
        ...data,
        company: data.company || null,
        email: data.email || null,
        phone: data.phone || null,
        address: data.address || null,
        notes: data.notes || null,
      }),
    onSuccess: () => {
      closePanel()
      invalidate()
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: FormState }) =>
      api.patch(`/contacts/${id}`, {
        ...data,
        company: data.company || null,
        email: data.email || null,
        phone: data.phone || null,
        address: data.address || null,
        notes: data.notes || null,
      }),
    onSuccess: () => {
      closePanel()
      invalidate()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/contacts/${id}`),
    onSuccess: () => {
      setDeleteId(null)
      invalidate()
    },
  })

  const openCreate = () => {
    setForm(EMPTY_FORM)
    setPanel({ open: true, mode: 'create' })
  }

  const openEdit = (c: Contact) => {
    setForm(contactToForm(c))
    setPanel({ open: true, mode: 'edit', id: c.id })
  }

  const closePanel = () => setPanel((p) => ({ ...p, open: false }))

  const handleSubmit = () => {
    if (!form.full_name.trim()) return
    if (panel.mode === 'create') createMutation.mutate(form)
    else if (panel.id) updateMutation.mutate({ id: panel.id, data: form })
  }

  const setField = <K extends keyof FormState>(key: K, val: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: val }))

  const isPending = createMutation.isPending || updateMutation.isPending

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold">Contacts</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Customers, suppliers, and internal contacts.
          </p>
        </div>
        <Button size="sm" onClick={openCreate}>
          <Plus className="w-3.5 h-3.5 mr-1.5" />
          Add Contact
        </Button>
      </div>

      {/* Type tabs */}
      <div className="flex items-center bg-muted rounded-md p-0.5 gap-0.5 w-fit">
        {TYPE_TABS.map((t) => (
          <button
            key={t.value}
            onClick={() => setTypeFilter(t.value)}
            className={cn(
              'px-3 py-1 text-xs font-medium rounded transition-colors',
              typeFilter === t.value
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Table */}
      <Card>
        <CardContent className="p-0 overflow-x-auto">
          {isLoading ? (
            <div className="p-4 space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : !contacts?.length ? (
            <div className="py-12 text-center">
              <p className="text-sm text-muted-foreground">
                No contacts yet.{' '}
                <button onClick={openCreate} className="text-primary hover:underline">
                  Add your first contact.
                </button>
              </p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/40">
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">
                    Name
                  </th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">
                    Company
                  </th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">
                    Type
                  </th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">
                    Email
                  </th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">
                    Phone
                  </th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold text-muted-foreground">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody>
                {contacts.map((c) => (
                  <tr
                    key={c.id}
                    className="border-b last:border-0 hover:bg-muted/30 transition-colors"
                  >
                    <td className="px-4 py-2.5 font-medium">{c.full_name}</td>
                    <td className="px-4 py-2.5 text-muted-foreground">{c.company ?? '—'}</td>
                    <td className="px-4 py-2.5">
                      <Badge variant={TYPE_VARIANT[c.contact_type as ContactType] ?? 'muted'}>
                        {c.contact_type}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 text-muted-foreground text-xs">
                      {c.email ?? '—'}
                    </td>
                    <td className="px-4 py-2.5 text-muted-foreground text-xs">
                      {c.phone ?? '—'}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      {deleteId === c.id ? (
                        <div className="inline-flex items-center gap-1.5">
                          <span className="text-xs text-muted-foreground">Delete?</span>
                          <Button
                            size="sm"
                            variant="destructive"
                            className="h-6 px-2 text-xs"
                            onClick={() => deleteMutation.mutate(c.id)}
                            disabled={deleteMutation.isPending}
                          >
                            <Check className="w-3 h-3" />
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-6 px-2 text-xs"
                            onClick={() => setDeleteId(null)}
                          >
                            <X className="w-3 h-3" />
                          </Button>
                        </div>
                      ) : (
                        <div className="inline-flex items-center gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 w-7 p-0"
                            onClick={() => openEdit(c)}
                          >
                            <Pencil className="w-3.5 h-3.5" />
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                            onClick={() => setDeleteId(c.id)}
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      {/* Slide-in Panel */}
      {panel.open && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 bg-black/30 z-40"
            onClick={closePanel}
          />

          {/* Panel */}
          <div className="fixed right-0 top-0 h-full w-full max-w-md bg-background border-l shadow-xl z-50 flex flex-col">
            {/* Panel Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b">
              <h2 className="font-semibold text-sm">
                {panel.mode === 'create' ? 'Add Contact' : 'Edit Contact'}
              </h2>
              <button onClick={closePanel} className="text-muted-foreground hover:text-foreground">
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Panel Body */}
            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">
                  Full name <span className="text-destructive">*</span>
                </label>
                <Input
                  value={form.full_name}
                  onChange={(e) => setField('full_name', e.target.value)}
                  placeholder="Jane Smith"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Company</label>
                <Input
                  value={form.company}
                  onChange={(e) => setField('company', e.target.value)}
                  placeholder="Acme Ltd"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Type</label>
                <NativeSelect
                  value={form.contact_type}
                  onChange={(e) => setField('contact_type', e.target.value as ContactType)}
                >
                  <option value="customer">Customer</option>
                  <option value="supplier">Supplier</option>
                  <option value="internal">Internal</option>
                  <option value="other">Other</option>
                </NativeSelect>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Email</label>
                <Input
                  type="email"
                  value={form.email}
                  onChange={(e) => setField('email', e.target.value)}
                  placeholder="jane@example.com"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Phone</label>
                <Input
                  value={form.phone}
                  onChange={(e) => setField('phone', e.target.value)}
                  placeholder="+44 7700 900000"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Address</label>
                <Input
                  value={form.address}
                  onChange={(e) => setField('address', e.target.value)}
                  placeholder="123 High St, London"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">Notes</label>
                <Textarea
                  value={form.notes}
                  onChange={(e) => setField('notes', e.target.value)}
                  placeholder="Any notes about this contact..."
                  rows={3}
                />
              </div>
            </div>

            {/* Panel Footer */}
            <div className="px-5 py-4 border-t flex items-center gap-3">
              <Button
                className="flex-1"
                onClick={handleSubmit}
                disabled={!form.full_name.trim() || isPending}
              >
                {isPending
                  ? 'Saving…'
                  : panel.mode === 'create'
                    ? 'Add Contact'
                    : 'Save Changes'}
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
