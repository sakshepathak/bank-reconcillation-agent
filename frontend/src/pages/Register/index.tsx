/**
 * Register / Add-your-business page — combined first-user bootstrap.
 *
 * Reachable only when /api/v1/auth/register-enabled returns true (no users
 * yet, or ALLOW_REGISTRATION=true). Otherwise the user is bounced to /login.
 *
 * Collects: email, password (confirmed), display name, business name.
 * Currency, VAT, financial year end etc. default sensibly and are editable
 * later in Settings — keeps onboarding to one screen.
 */
import { useEffect, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Loader2 } from 'lucide-react'
import MatchaMark from '@/components/MatchaMark'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { useAuth, fetchRegisterEnabled } from '@/lib/auth-context'
import { ApiError } from '@/lib/api'

const schema = z
  .object({
    email: z
      .string()
      .min(3, 'Email is required')
      .includes('@', { message: 'Must look like an email' }),
    name: z.string().min(1, 'Your name is required'),
    org_name: z.string().min(1, 'Business name is required'),
    password: z.string().min(8, 'Password must be at least 8 characters'),
    confirm: z.string(),
  })
  .refine((data) => data.password === data.confirm, {
    path: ['confirm'],
    message: "Passwords don't match",
  })

type FormValues = z.infer<typeof schema>

export default function Register() {
  const { user, register: registerUser } = useAuth()
  const navigate = useNavigate()
  const [serverError, setServerError] = useState<string | null>(null)
  const [probe, setProbe] = useState<'loading' | 'open' | 'closed'>('loading')

  useEffect(() => {
    fetchRegisterEnabled()
      .then((enabled) => setProbe(enabled ? 'open' : 'closed'))
      .catch(() => setProbe('closed'))
  }, [])

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  if (user) return <Navigate to="/dashboard" replace />
  if (probe === 'loading') return null
  if (probe === 'closed') return <Navigate to="/login" replace />

  async function onSubmit(values: FormValues) {
    setServerError(null)
    try {
      await registerUser({
        email: values.email,
        password: values.password,
        name: values.name,
        org_name: values.org_name,
      })
      navigate('/dashboard', { replace: true })
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : 'Registration failed')
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 to-matcha-50 px-4 py-10">
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader className="space-y-1 pb-4">
          <div className="flex items-center gap-2.5 pb-2">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-matcha-600 to-matcha-700 flex items-center justify-center text-white">
              <MatchaMark className="w-6 h-6" />
            </div>
            <div>
              <p className="font-display text-lg font-semibold text-foreground leading-tight">Matcha</p>
              <p className="text-xs text-muted-foreground">
                Create your account and first organization
              </p>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="email" className="text-sm font-medium text-foreground">Email</label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                autoFocus
                placeholder="you@example.com"
                {...register('email')}
              />
              {errors.email && <p className="text-xs text-destructive">{errors.email.message}</p>}
            </div>

            <div className="space-y-1.5">
              <label htmlFor="name" className="text-sm font-medium text-foreground">Your name</label>
              <Input id="name" placeholder="Sakshi Pathak" {...register('name')} />
              {errors.name && <p className="text-xs text-destructive">{errors.name.message}</p>}
            </div>

            <div className="space-y-1.5">
              <label htmlFor="org_name" className="text-sm font-medium text-foreground">Business name</label>
              <Input id="org_name" placeholder="Acme Ltd" {...register('org_name')} />
              {errors.org_name && (
                <p className="text-xs text-destructive">{errors.org_name.message}</p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label htmlFor="password" className="text-sm font-medium text-foreground">Password</label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="new-password"
                  placeholder="••••••••"
                  {...register('password')}
                />
                {errors.password && (
                  <p className="text-xs text-destructive">{errors.password.message}</p>
                )}
              </div>
              <div className="space-y-1.5">
                <label htmlFor="confirm" className="text-sm font-medium text-foreground">Confirm</label>
                <Input
                  id="confirm"
                  type="password"
                  autoComplete="new-password"
                  placeholder="••••••••"
                  {...register('confirm')}
                />
                {errors.confirm && (
                  <p className="text-xs text-destructive">{errors.confirm.message}</p>
                )}
              </div>
            </div>

            {serverError && (
              <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                {serverError}
              </div>
            )}

            <Button type="submit" className="w-full" disabled={isSubmitting}>
              {isSubmitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Creating your account…
                </>
              ) : (
                'Create account & business'
              )}
            </Button>

            <p className="text-center text-sm text-muted-foreground pt-2">
              Already have an account?{' '}
              <Link to="/login" className="text-matcha-600 font-medium hover:underline">
                Sign in
              </Link>
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
