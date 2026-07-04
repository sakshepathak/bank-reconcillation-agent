import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Check, AlertTriangle, Download, Loader2, Monitor, Sun, Moon } from 'lucide-react'
import { api } from '@/lib/api'
import { useAuth, type OrgFull } from '@/lib/auth-context'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { NativeSelect } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import { useTheme, type ThemeChoice } from '@/lib/theme-context'
import type { UserProfile, Company, Service, TaxTreatment } from '@/types'

type Tab = 'profile' | 'organisation' | 'services' | 'appearance'

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

// ── Organisation Tab (details + danger zone) ──────────────────────────────────

function OrganisationTab() {
  const { user, deleteOrg } = useAuth()
  const queryClient = useQueryClient()
  const [saved, setSaved] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const [exporting, setExporting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: org, isLoading: orgLoading } = useQuery<OrgFull>({
    queryKey: ['org-current'],
    queryFn: () => api.get('/orgs/current').then((r) => r.data),
  })
  const { data: company, isLoading: companyLoading } = useQuery<Company>({
    queryKey: ['company'],
    queryFn: () => api.get('/company').then((r) => r.data),
  })

  // One unified form over BOTH the Organization (identity) and CompanyProfile
  // (rich details) records — the user edits everything in one place. Overlapping
  // fields (industry, VAT, tax) are written to both on save so they stay in sync.
  const [form, setForm] = useState({
    name: '', country: '', currency: '', industry: '',
    website: '', phone: '', address: '', about: '', registration_number: '',
    vat_registered: false, vat_number: '', tax_treatment: 'exclusive' as TaxTreatment,
  })

  useEffect(() => {
    if (org && company) {
      setForm({
        name: org.name,
        country: org.country ?? '',
        currency: org.currency,
        // Prefer the org-level value, fall back to the profile's.
        industry: org.industry ?? company.industry ?? '',
        website: company.website ?? '',
        phone: company.phone ?? '',
        address: company.address ?? '',
        about: company.about ?? '',
        registration_number: company.registration_number ?? '',
        vat_registered: org.vat_registered,
        vat_number: org.vat_number ?? company.vat_number ?? '',
        tax_treatment: (org.tax_treatment as TaxTreatment) ?? 'exclusive',
      })
    }
  }, [org, company])

  const set = <K extends keyof typeof form>(k: K, v: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [k]: v }))

  const saveMutation = useMutation({
    mutationFn: async () => {
      // Organisation identity (name shown in switcher, country/currency, etc.)
      await api.patch('/orgs/current', {
        name: form.name,
        country: form.country || undefined,
        currency: form.currency || undefined,
        industry: form.industry || null,
        vat_registered: form.vat_registered,
        vat_number: form.vat_registered ? (form.vat_number || null) : null,
        tax_treatment: form.tax_treatment,
      })
      // Rich company profile (description, contact details) — keep overlapping
      // fields mirrored so /company and the future KB read consistent values.
      await api.put('/company', {
        company_name: form.name,
        about: form.about || null,
        industry: form.industry || null,
        website: form.website || null,
        phone: form.phone || null,
        address: form.address || null,
        registration_number: form.registration_number || null,
        vat_registered: form.vat_registered,
        vat_number: form.vat_registered ? (form.vat_number || null) : null,
        tax_treatment: form.tax_treatment,
      })
    },
    onSuccess: () => {
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
      // Refresh org details, company profile, and auth-me (name drives the switcher).
      queryClient.invalidateQueries({ queryKey: ['org-current'] })
      queryClient.invalidateQueries({ queryKey: ['company'] })
      queryClient.invalidateQueries({ queryKey: ['auth-me'] })
    },
  })

  if (orgLoading || companyLoading || !org) return <Skeleton className="h-64 w-full" />

  const isAdmin = org.role === 'admin'
  const otherOrgCount = (user?.orgs.length ?? 1) - 1

  const downloadBackup = async () => {
    setExporting(true)
    setError(null)
    try {
      const { data } = await api.get(`/orgs/${org.id}/export`)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${org.name.replace(/[^a-z0-9]+/gi, '_')}_backup.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Export failed')
    } finally {
      setExporting(false)
    }
  }

  const confirmDelete = async () => {
    setDeleting(true)
    setError(null)
    try {
      // On success the session's current org is reset to null; RequireOrg then
      // redirects to /onboarding (the org picker). No manual navigation needed.
      await deleteOrg(org.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Delete failed')
      setDeleting(false)
    }
  }

  return (
    <div className="space-y-5 max-w-lg">
      {/* Editable org + company details (one place — no separate Company tab) */}
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          Organisation details
        </p>
        <Badge variant="muted" className="capitalize">{org.role ?? 'member'}</Badge>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="col-span-2 space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Organisation name</label>
          <Input value={form.name} onChange={(e) => set('name', e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Industry</label>
          <Input
            value={form.industry}
            onChange={(e) => set('industry', e.target.value)}
            placeholder="e.g. Hospitality"
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Country</label>
            <Input
              value={form.country}
              onChange={(e) => set('country', e.target.value.toUpperCase().slice(0, 2))}
              placeholder="GB"
              maxLength={2}
              className="font-mono uppercase"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Currency</label>
            <Input
              value={form.currency}
              onChange={(e) => set('currency', e.target.value.toUpperCase().slice(0, 3))}
              placeholder="GBP"
              maxLength={3}
              className="font-mono uppercase"
            />
          </div>
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Website</label>
          <Input
            value={form.website}
            onChange={(e) => set('website', e.target.value)}
            placeholder="https://example.com"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Phone</label>
          <Input value={form.phone} onChange={(e) => set('phone', e.target.value)} />
        </div>
        <div className="col-span-2 space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Address</label>
          <Input value={form.address} onChange={(e) => set('address', e.target.value)} />
        </div>
        <div className="col-span-2 space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">
            About — what this company does
          </label>
          <Textarea
            value={form.about}
            onChange={(e) => set('about', e.target.value)}
            placeholder="Describe the business, what it sells, who its customers are…"
            rows={3}
          />
          <p className="text-[11px] text-muted-foreground">
            This feeds the assistant's knowledge base about your company.
          </p>
        </div>
      </div>

      {/* VAT / Tax */}
      <div className="border rounded-lg p-4 space-y-4">
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">VAT & Tax</p>
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Registration number</label>
          <Input
            value={form.registration_number}
            onChange={(e) => set('registration_number', e.target.value)}
            placeholder="e.g. 12345678"
          />
        </div>
        <div className="flex items-center gap-3">
          <input
            type="checkbox"
            id="org-vat-reg"
            checked={form.vat_registered}
            onChange={(e) => set('vat_registered', e.target.checked)}
            className="w-4 h-4 accent-primary"
          />
          <label htmlFor="org-vat-reg" className="text-sm cursor-pointer">VAT registered</label>
        </div>
        {form.vat_registered && (
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">VAT number</label>
            <Input
              value={form.vat_number}
              onChange={(e) => set('vat_number', e.target.value)}
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

      <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending || !form.name.trim()}>
        {saved ? (
          <><Check className="w-3.5 h-3.5 mr-1.5" /> Saved</>
        ) : saveMutation.isPending ? 'Saving…' : 'Save changes'}
      </Button>

      {/* Danger zone */}
      <div className="border border-destructive/40 rounded-lg p-4 space-y-3 bg-destructive/5">
        <div className="flex items-center gap-2 text-destructive">
          <AlertTriangle className="w-4 h-4" />
          <p className="text-sm font-semibold">Danger zone</p>
        </div>
        <p className="text-sm text-muted-foreground">
          Permanently delete <span className="font-semibold text-foreground">{org.name}</span> and
          everything in it — invoices, bills, contacts, bank statements, reconciliations and its
          knowledge base. This cannot be undone. Download a backup first.
        </p>
        {!isAdmin ? (
          <p className="text-xs text-muted-foreground italic">
            Only an admin of this organisation can delete it.
          </p>
        ) : (
          <Button variant="destructive" size="sm" onClick={() => { setConfirmOpen(true); setTyped('') }}>
            <Trash2 className="w-3.5 h-3.5 mr-1.5" />
            Delete this organisation
          </Button>
        )}
      </div>

      {/* Confirm modal */}
      {confirmOpen && (
        <>
          <div className="fixed inset-0 bg-black/40 z-40" onClick={() => !deleting && setConfirmOpen(false)} />
          <div className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-md bg-background border rounded-xl shadow-2xl p-5 space-y-4">
            <div className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="w-5 h-5" />
              <h3 className="font-semibold">Delete {org.name}?</h3>
            </div>
            <p className="text-sm text-muted-foreground">
              This permanently erases all data for this organisation. There is no undo. We strongly
              recommend downloading a backup first.
            </p>

            <Button variant="outline" size="sm" onClick={downloadBackup} disabled={exporting} className="w-full">
              {exporting ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <Download className="w-3.5 h-3.5 mr-1.5" />}
              {exporting ? 'Preparing backup…' : 'Download backup (JSON)'}
            </Button>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">
                Type <span className="font-mono font-semibold text-foreground">{org.name}</span> to confirm
              </label>
              <Input
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                placeholder={org.name}
                autoFocus
                disabled={deleting}
              />
            </div>

            {error && <p className="text-xs text-destructive">{error}</p>}

            <p className="text-xs text-muted-foreground">
              {otherOrgCount > 0
                ? `You'll be asked to pick one of your other ${otherOrgCount} organisation(s) afterwards.`
                : `You have no other organisations — you'll be taken to create a new one.`}
            </p>

            <div className="flex items-center gap-2 pt-1">
              <Button
                variant="destructive"
                className="flex-1"
                onClick={confirmDelete}
                disabled={typed !== org.name || deleting}
              >
                {deleting ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5 mr-1.5" />}
                {deleting ? 'Deleting…' : 'Permanently delete'}
              </Button>
              <Button variant="outline" onClick={() => setConfirmOpen(false)} disabled={deleting}>
                Cancel
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// ── Appearance Tab (theme) ────────────────────────────────────────────────────

function AppearanceTab() {
  const { choice, resolved, setChoice } = useTheme()

  const options: { id: ThemeChoice; label: string; icon: typeof Sun; hint: string }[] = [
    { id: 'system', label: 'System', icon: Monitor, hint: 'Follow your device' },
    { id: 'light',  label: 'Light',  icon: Sun,     hint: 'Warm paper' },
    { id: 'dark',   label: 'Dark',   icon: Moon,    hint: 'Steeped bowl' },
  ]

  return (
    <div className="space-y-5 max-w-lg">
      <div>
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Theme</p>
        <p className="text-sm text-muted-foreground mt-1">
          Choose how Matcha looks.{choice === 'system' && ` Following your device — currently ${resolved}.`}
        </p>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {options.map(({ id, label, icon: Icon, hint }) => {
          const active = choice === id
          return (
            <button
              key={id}
              type="button"
              onClick={() => setChoice(id)}
              aria-pressed={active}
              className={cn(
                'relative flex flex-col items-start gap-2.5 rounded-xl border p-4 text-left transition-all',
                active
                  ? 'border-primary ring-2 ring-primary/30 bg-primary-subtle/50'
                  : 'border-border hover:border-primary/40 hover:bg-muted/50',
              )}
            >
              {active && <Check className="absolute top-3 right-3 w-4 h-4 text-primary" />}
              <div className={cn(
                'w-9 h-9 rounded-lg flex items-center justify-center',
                active ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground',
              )}>
                <Icon className="w-5 h-5" />
              </div>
              <div>
                <p className="text-sm font-semibold text-foreground">{label}</p>
                <p className="text-xs text-muted-foreground">{hint}</p>
              </div>
            </button>
          )
        })}
      </div>

      {/* Live preview — a few themed surfaces so the choice is tangible */}
      <div className="rounded-xl border bg-card shadow-sm p-4">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mb-3">Preview</p>
        <div className="flex items-center gap-3 flex-wrap">
          <span className="inline-flex items-center h-8 px-3 rounded-lg bg-primary text-primary-foreground text-sm font-medium">Primary</span>
          <span className="inline-flex items-center h-8 px-3 rounded-lg bg-muted text-foreground text-sm">Surface</span>
          <Badge variant="success">matched</Badge>
          <Badge variant="warning">pending</Badge>
          <span className="font-mono text-sm text-foreground">£33,875.14</span>
        </div>
      </div>
    </div>
  )
}

// ── Main Settings Page ────────────────────────────────────────────────────────

const TABS: { id: Tab; label: string }[] = [
  { id: 'profile', label: 'Profile' },
  { id: 'organisation', label: 'Organisation' },
  { id: 'services', label: 'Services & Products' },
  { id: 'appearance', label: 'Appearance' },
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
        {tab === 'organisation' && <OrganisationTab />}
        {tab === 'services' && <ServicesTab />}
        {tab === 'appearance' && <AppearanceTab />}
      </div>
    </div>
  )
}
