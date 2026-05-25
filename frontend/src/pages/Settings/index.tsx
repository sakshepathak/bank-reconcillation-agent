import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Check } from 'lucide-react'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { NativeSelect } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import type { UserProfile, Company, Service, TaxTreatment } from '@/types'

type Tab = 'profile' | 'company' | 'services'

// ── Profile Tab ───────────────────────────────────────────────────────────────

function ProfileTab() {
  const queryClient = useQueryClient()
  const [saved, setSaved] = useState(false)
  const [form, setForm] = useState({ name: '', role: '', email: '' })

  const { data, isLoading } = useQuery<UserProfile>({
    queryKey: ['profile'],
    queryFn: () => api.get('/profile/').then((r) => r.data),
  })

  useEffect(() => {
    if (data) setForm({ name: data.name, role: data.role, email: data.email ?? '' })
  }, [data])

  const saveMutation = useMutation({
    mutationFn: () =>
      api.put('/profile/', { name: form.name, role: form.role, email: form.email || null }),
    onSuccess: () => {
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
      queryClient.invalidateQueries({ queryKey: ['profile'] })
    },
  })

  if (isLoading) return <Skeleton className="h-48 w-full" />

  return (
    <div className="space-y-4 max-w-md">
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">Full name</label>
        <Input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
      </div>
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">Role</label>
        <Input
          value={form.role}
          onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
          placeholder="e.g. Senior Accountant"
        />
      </div>
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">Email</label>
        <Input
          type="email"
          value={form.email}
          onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
          placeholder="you@company.com"
        />
      </div>
      <Button
        onClick={() => saveMutation.mutate()}
        disabled={saveMutation.isPending || !form.name.trim()}
      >
        {saved ? (
          <>
            <Check className="w-3.5 h-3.5 mr-1.5" /> Saved
          </>
        ) : saveMutation.isPending ? (
          'Saving…'
        ) : (
          'Save Profile'
        )}
      </Button>
    </div>
  )
}

// ── Company Tab ───────────────────────────────────────────────────────────────

function CompanyTab() {
  const queryClient = useQueryClient()
  const [saved, setSaved] = useState(false)
  const [form, setForm] = useState<Omit<Company, 'id' | 'updated_at'>>({
    company_name: '',
    about: null,
    industry: null,
    website: null,
    phone: null,
    address: null,
    registration_number: null,
    vat_registered: false,
    vat_number: null,
    tax_treatment: 'exclusive',
  })

  const { data, isLoading } = useQuery<Company>({
    queryKey: ['company'],
    queryFn: () => api.get('/company').then((r) => r.data),
  })

  useEffect(() => {
    if (data) {
      setForm({
        company_name: data.company_name,
        about: data.about,
        industry: data.industry,
        website: data.website,
        phone: data.phone,
        address: data.address,
        registration_number: data.registration_number,
        vat_registered: data.vat_registered,
        vat_number: data.vat_number,
        tax_treatment: data.tax_treatment,
      })
    }
  }, [data])

  const saveMutation = useMutation({
    mutationFn: () => api.put('/company', form),
    onSuccess: () => {
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
      queryClient.invalidateQueries({ queryKey: ['company'] })
    },
  })

  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [k]: v }))

  if (isLoading) return <Skeleton className="h-64 w-full" />

  return (
    <div className="space-y-4 max-w-lg">
      <div className="grid grid-cols-2 gap-4">
        <div className="col-span-2 space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Company name</label>
          <Input value={form.company_name} onChange={(e) => set('company_name', e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Industry</label>
          <Input
            value={form.industry ?? ''}
            onChange={(e) => set('industry', e.target.value || null)}
            placeholder="e.g. Accounting"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Phone</label>
          <Input
            value={form.phone ?? ''}
            onChange={(e) => set('phone', e.target.value || null)}
          />
        </div>
        <div className="col-span-2 space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Website</label>
          <Input
            value={form.website ?? ''}
            onChange={(e) => set('website', e.target.value || null)}
            placeholder="https://example.com"
          />
        </div>
        <div className="col-span-2 space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Address</label>
          <Input
            value={form.address ?? ''}
            onChange={(e) => set('address', e.target.value || null)}
          />
        </div>
        <div className="col-span-2 space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">About</label>
          <Textarea
            value={form.about ?? ''}
            onChange={(e) => set('about', e.target.value || null)}
            placeholder="Short description of the company…"
          />
        </div>
      </div>

      {/* VAT / Tax */}
      <div className="border rounded-lg p-4 space-y-4">
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          VAT & Tax
        </p>
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Registration number</label>
          <Input
            value={form.registration_number ?? ''}
            onChange={(e) => set('registration_number', e.target.value || null)}
            placeholder="e.g. 12345678"
          />
        </div>
        <div className="flex items-center gap-3">
          <input
            type="checkbox"
            id="vat-reg"
            checked={form.vat_registered}
            onChange={(e) => set('vat_registered', e.target.checked)}
            className="w-4 h-4 accent-primary"
          />
          <label htmlFor="vat-reg" className="text-sm cursor-pointer">
            VAT registered
          </label>
        </div>
        {form.vat_registered && (
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">VAT number</label>
            <Input
              value={form.vat_number ?? ''}
              onChange={(e) => set('vat_number', e.target.value || null)}
              placeholder="GB123456789"
            />
          </div>
        )}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Tax treatment</label>
          <NativeSelect
            value={form.tax_treatment}
            onChange={(e) => set('tax_treatment', e.target.value as TaxTreatment)}
          >
            <option value="exclusive">Tax exclusive (VAT added on top)</option>
            <option value="inclusive">Tax inclusive (VAT within price)</option>
            <option value="exempt">Exempt</option>
          </NativeSelect>
        </div>
      </div>

      <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
        {saved ? (
          <>
            <Check className="w-3.5 h-3.5 mr-1.5" /> Saved
          </>
        ) : saveMutation.isPending ? (
          'Saving…'
        ) : (
          'Save Company'
        )}
      </Button>
    </div>
  )
}

// ── Services Tab ──────────────────────────────────────────────────────────────

function ServicesTab() {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({ name: '', description: '', service_category: 'service', vat_applicable: true })
  const [deleteId, setDeleteId] = useState<number | null>(null)

  const { data: services, isLoading } = useQuery<Service[]>({
    queryKey: ['services'],
    queryFn: () => api.get('/services').then((r) => r.data),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      api.post('/services', {
        name: form.name,
        description: form.description || null,
        service_category: form.service_category,
        vat_applicable: form.vat_applicable,
      }),
    onSuccess: () => {
      setForm({ name: '', description: '', service_category: 'service', vat_applicable: true })
      queryClient.invalidateQueries({ queryKey: ['services'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/services/${id}`),
    onSuccess: () => {
      setDeleteId(null)
      queryClient.invalidateQueries({ queryKey: ['services'] })
    },
  })

  return (
    <div className="space-y-4">
      {/* Add form */}
      <Card>
        <CardContent className="py-4 px-4 space-y-3">
          <p className="text-xs font-semibold text-muted-foreground">Add Service / Product</p>
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2 space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Name</label>
              <Input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="e.g. Monthly Retainer"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Category</label>
              <NativeSelect
                value={form.service_category}
                onChange={(e) => setForm((f) => ({ ...f, service_category: e.target.value }))}
              >
                <option value="service">Service</option>
                <option value="product">Product</option>
              </NativeSelect>
            </div>
            <div className="space-y-1.5 flex flex-col justify-end">
              <div className="flex items-center gap-2 h-9">
                <input
                  type="checkbox"
                  id="vat-svc"
                  checked={form.vat_applicable}
                  onChange={(e) => setForm((f) => ({ ...f, vat_applicable: e.target.checked }))}
                  className="w-4 h-4 accent-primary"
                />
                <label htmlFor="vat-svc" className="text-sm cursor-pointer">VAT applicable</label>
              </div>
            </div>
            <div className="col-span-2 space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Description (optional)</label>
              <Input
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                placeholder="Brief description…"
              />
            </div>
          </div>
          <Button
            size="sm"
            onClick={() => createMutation.mutate()}
            disabled={!form.name.trim() || createMutation.isPending}
          >
            <Plus className="w-3.5 h-3.5 mr-1.5" />
            Add
          </Button>
        </CardContent>
      </Card>

      {/* List */}
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="p-4 space-y-2">
              {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
            </div>
          ) : !services?.length ? (
            <div className="py-10 text-center text-sm text-muted-foreground">
              No services or products yet.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/40">
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">Name</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">Category</th>
                  <th className="px-4 py-2.5 text-center text-xs font-semibold text-muted-foreground">VAT</th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">Description</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {services.map((s) => (
                  <tr key={s.id} className="border-b last:border-0 hover:bg-muted/30 transition-colors">
                    <td className="px-4 py-2.5 font-medium">{s.name}</td>
                    <td className="px-4 py-2.5">
                      <Badge variant={s.service_category === 'service' ? 'info' : 'muted'}>
                        {s.service_category}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      {s.vat_applicable ? (
                        <Badge variant="success">Yes</Badge>
                      ) : (
                        <Badge variant="muted">No</Badge>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground">{s.description ?? '—'}</td>
                    <td className="px-4 py-2.5 text-right">
                      {deleteId === s.id ? (
                        <div className="inline-flex items-center gap-1.5">
                          <span className="text-xs text-muted-foreground">Delete?</span>
                          <Button size="sm" variant="destructive" className="h-6 px-2 text-xs"
                            onClick={() => deleteMutation.mutate(s.id)} disabled={deleteMutation.isPending}>
                            Yes
                          </Button>
                          <Button size="sm" variant="outline" className="h-6 px-2 text-xs"
                            onClick={() => setDeleteId(null)}>
                            No
                          </Button>
                        </div>
                      ) : (
                        <Button size="sm" variant="ghost" className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                          onClick={() => setDeleteId(s.id)}>
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
    </div>
  )
}

// ── Main Settings Page ────────────────────────────────────────────────────────

const TABS: { id: Tab; label: string }[] = [
  { id: 'profile', label: 'Profile' },
  { id: 'company', label: 'Company' },
  { id: 'services', label: 'Services & Products' },
]

export default function Settings() {
  const [tab, setTab] = useState<Tab>('profile')

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold">Settings</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Manage your profile, company details, and service catalogue.
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex items-center border-b gap-0">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              'px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors',
              tab === t.id
                ? 'border-primary text-foreground'
                : 'border-transparent text-muted-foreground hover:text-foreground',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="pt-1">
        {tab === 'profile' && <ProfileTab />}
        {tab === 'company' && <CompanyTab />}
        {tab === 'services' && <ServicesTab />}
      </div>
    </div>
  )
}
