/**
 * "Add your business" page — Xero-style multi-field onboarding.
 *
 * Reached two ways:
 *   1. A logged-in user with 0 orgs gets force-redirected here by RequireOrg.
 *   2. A logged-in user clicks "+ Add new organisation" in the OrgSwitcher.
 *
 * On submit: POST /api/v1/orgs → backend creates the org, adds an admin
 * membership, and switches the session's current_org_id to the new org.
 * We then refresh /auth/me so the sidebar reflects the new org, and bounce
 * to /dashboard.
 *
 * Defaults are UK because that's the primary target market. The country
 * dropdown lists a handful of common options + the form can be saved with
 * any 2-letter code if you edit Settings later.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Loader2, Building2 } from 'lucide-react'

import { ApiError } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { Card, CardContent, CardHeader } from '@/components/ui/card'

// ── Reference lists ─────────────────────────────────────────────────────────
// Common combos shown to the user. They can save any ISO-2 / ISO-4217 code
// via the Settings page later. Country drives the currency default but the
// user can override.

const COUNTRY_OPTIONS: { code: string; label: string; currency: string }[] = [
  { code: 'GB', label: 'United Kingdom', currency: 'GBP' },
  { code: 'IN', label: 'India',          currency: 'INR' },
  { code: 'US', label: 'United States',  currency: 'USD' },
  { code: 'CA', label: 'Canada',         currency: 'CAD' },
  { code: 'AU', label: 'Australia',      currency: 'AUD' },
  { code: 'NZ', label: 'New Zealand',    currency: 'NZD' },
  { code: 'IE', label: 'Ireland',        currency: 'EUR' },
  { code: 'DE', label: 'Germany',        currency: 'EUR' },
  { code: 'FR', label: 'France',         currency: 'EUR' },
  { code: 'SG', label: 'Singapore',      currency: 'SGD' },
]

const CURRENCY_OPTIONS = ['GBP', 'INR', 'USD', 'CAD', 'AUD', 'NZD', 'EUR', 'SGD']

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

const TAX_TREATMENTS = [
  { value: 'exclusive', label: 'Tax exclusive (amounts entered before tax)' },
  { value: 'inclusive', label: 'Tax inclusive (amounts entered include tax)' },
  { value: 'exempt',    label: 'No tax (VAT not registered / exempt)' },
]

const schema = z.object({
  name: z.string().min(1, 'Business name is required').max(120),
  country: z.string().length(2),
  currency: z.string().length(3),
  industry: z.string().optional(),
  vat_registered: z.boolean(),
  vat_number: z.string().optional(),
  tax_treatment: z.string(),
  financial_year_end_day: z.number().int().min(1).max(31),
  financial_year_end_month: z.number().int().min(1).max(12),
})

type FormValues = z.infer<typeof schema>

const DEFAULTS: FormValues = {
  name: '',
  country: 'GB',
  currency: 'GBP',
  industry: '',
  vat_registered: false,
  vat_number: '',
  tax_treatment: 'exclusive',
  financial_year_end_day: 5,    // UK tax year ends 5 April
  financial_year_end_month: 4,
}

export default function Onboarding() {
  const navigate = useNavigate()
  const { user, createOrg, switchOrg } = useAuth()
  const [serverError, setServerError] = useState<string | null>(null)
  const [switchingId, setSwitchingId] = useState<number | null>(null)

  // Pick one of the user's existing orgs (the "no org selected" path after a
  // delete, or simply choosing a different set of books). Switching sets the
  // session's current_org_id and drops us into the app.
  async function handleSelectExisting(orgId: number) {
    setSwitchingId(orgId)
    setServerError(null)
    try {
      await switchOrg(orgId)
      navigate('/dashboard', { replace: true })
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : 'Could not switch organisation')
      setSwitchingId(null)
    }
  }

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    watch,
    setValue,
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: DEFAULTS,
  })

  const country = watch('country')
  const vatRegistered = watch('vat_registered')
  const taxTreatment = watch('tax_treatment')
  const day = watch('financial_year_end_day')
  const month = watch('financial_year_end_month')

  // Auto-update currency to match country when the user picks a new country.
  function handleCountryChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const newCode = e.target.value
    setValue('country', newCode)
    const match = COUNTRY_OPTIONS.find((c) => c.code === newCode)
    if (match) setValue('currency', match.currency)
  }

  async function onSubmit(values: FormValues) {
    setServerError(null)
    try {
      // createOrg in auth-context drops all cached org-scoped queries AND
      // awaits the /auth/me refetch, so by the time we navigate the sidebar
      // and route guards see the new current_org_id with no stale data.
      await createOrg({
        ...values,
        industry: values.industry?.trim() || null,
        vat_number: values.vat_registered ? (values.vat_number?.trim() || null) : null,
      })
      navigate('/dashboard', { replace: true })
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : 'Could not create organisation')
    }
  }

  const hasExistingOrgs = (user?.orgs.length ?? 0) > 0
  const noOrgSelected = (user?.current_org_id ?? null) === null

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 to-indigo-50 px-4 py-10">
      <Card className="w-full max-w-2xl shadow-lg">
        <CardHeader className="space-y-1 pb-4 border-b">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-lg bg-gradient-to-br from-indigo-600 to-indigo-700 flex items-center justify-center flex-shrink-0">
              <Building2 className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-foreground">
                {hasExistingOrgs && noOrgSelected ? 'Select an organisation' : 'Add your business'}
              </h1>
              <p className="text-xs text-muted-foreground">
                {hasExistingOrgs && noOrgSelected
                  ? 'No organisation is selected. Pick one to continue, or create a new one.'
                  : hasExistingOrgs
                  ? "You'll be switched to this organisation once it's created."
                  : 'Tell us about your business to get started. You can change everything later in Settings.'}
              </p>
            </div>
          </div>
        </CardHeader>

        <CardContent className="pt-5 space-y-6">
          {/* Existing-org picker — shown whenever the user already has orgs */}
          {hasExistingOrgs && (
            <div className="space-y-2">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                Your organisations
              </p>
              <div className="space-y-1.5">
                {user!.orgs.map((o) => (
                  <button
                    key={o.id}
                    type="button"
                    onClick={() => handleSelectExisting(o.id)}
                    disabled={switchingId !== null}
                    className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border border-slate-200 bg-white hover:bg-indigo-50/60 hover:border-indigo-300 transition-colors text-left disabled:opacity-60"
                  >
                    <div className="w-8 h-8 rounded-md bg-indigo-100 flex items-center justify-center flex-shrink-0">
                      <Building2 className="w-4 h-4 text-indigo-600" />
                    </div>
                    <span className="flex-1 text-sm font-medium truncate">{o.name}</span>
                    <span className="text-xs text-muted-foreground capitalize">{o.role}</span>
                    {switchingId === o.id && <Loader2 className="w-4 h-4 animate-spin text-indigo-600" />}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-3 pt-2">
                <div className="flex-1 h-px bg-slate-200" />
                <span className="text-xs text-muted-foreground">or add a new business</span>
                <div className="flex-1 h-px bg-slate-200" />
              </div>
            </div>
          )}

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
            {/* Business name */}
            <div className="space-y-1.5">
              <label htmlFor="name" className="text-sm font-medium text-foreground">
                Business name <span className="text-destructive">*</span>
              </label>
              <Input
                id="name"
                placeholder="Acme Ltd"
                autoFocus
                {...register('name')}
              />
              {errors.name && <p className="text-xs text-destructive">{errors.name.message}</p>}
            </div>

            {/* Industry */}
            <div className="space-y-1.5">
              <label htmlFor="industry" className="text-sm font-medium text-foreground">
                Industry
              </label>
              <Input
                id="industry"
                placeholder="e.g. consulting, retail, services"
                {...register('industry')}
              />
            </div>

            {/* Country + currency */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label htmlFor="country" className="text-sm font-medium text-foreground">
                  Country
                </label>
                <NativeSelect id="country" value={country} onChange={handleCountryChange}>
                  {COUNTRY_OPTIONS.map((c) => (
                    <option key={c.code} value={c.code}>{c.label}</option>
                  ))}
                </NativeSelect>
              </div>
              <div className="space-y-1.5">
                <label htmlFor="currency" className="text-sm font-medium text-foreground">
                  Currency
                </label>
                <NativeSelect id="currency" {...register('currency')}>
                  {CURRENCY_OPTIONS.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </NativeSelect>
              </div>
            </div>

            {/* Financial year end */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">
                Last day of your financial year
              </label>
              <div className="grid grid-cols-2 gap-3">
                <NativeSelect
                  value={day}
                  onChange={(e) => setValue('financial_year_end_day', Number(e.target.value))}
                >
                  {Array.from({ length: 31 }, (_, i) => i + 1).map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </NativeSelect>
                <NativeSelect
                  value={month}
                  onChange={(e) => setValue('financial_year_end_month', Number(e.target.value))}
                >
                  {MONTHS.map((m, i) => (
                    <option key={m} value={i + 1}>{m}</option>
                  ))}
                </NativeSelect>
              </div>
              <p className="text-xs text-muted-foreground">
                UK businesses typically use 5 April. Indian businesses use 31 March.
              </p>
            </div>

            {/* Tax treatment */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">
                Tax treatment
              </label>
              <NativeSelect
                value={taxTreatment}
                onChange={(e) => setValue('tax_treatment', e.target.value)}
              >
                {TAX_TREATMENTS.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </NativeSelect>
            </div>

            {/* VAT */}
            <div className="space-y-2 rounded-lg border border-slate-200 px-4 py-3 bg-slate-50/50">
              <label className="flex items-center gap-2.5 cursor-pointer text-sm font-medium text-foreground">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-slate-300 accent-indigo-600"
                  {...register('vat_registered')}
                />
                <span>This business is VAT registered</span>
              </label>
              {vatRegistered && (
                <div className="pl-6 space-y-1.5">
                  <label htmlFor="vat_number" className="text-xs font-medium text-muted-foreground">
                    VAT number
                  </label>
                  <Input
                    id="vat_number"
                    placeholder="GB123456789"
                    {...register('vat_number')}
                  />
                </div>
              )}
            </div>

            {serverError && (
              <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                {serverError}
              </div>
            )}

            <div className="flex items-center gap-3 pt-1">
              {hasExistingOrgs && !noOrgSelected && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => navigate('/dashboard')}
                  disabled={isSubmitting}
                >
                  Cancel
                </Button>
              )}
              <Button type="submit" className="flex-1" disabled={isSubmitting}>
                {isSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Creating business…
                  </>
                ) : (
                  'Create business'
                )}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
