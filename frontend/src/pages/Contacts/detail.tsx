import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Plus, Trash2 } from 'lucide-react'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { cn, formatCurrency, formatDate } from '@/lib/utils'
import type { ContactDetail, ContactType, DocumentStatus } from '@/types'

const TYPE_VARIANT: Record<ContactType, 'info' | 'success' | 'muted' | 'warning'> = {
  customer: 'info',
  supplier: 'success',
  internal: 'muted',
  other: 'warning',
}

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

export default function ContactDetailPage() {
  const { id } = useParams<{ id: string }>()
  const contactId = Number(id)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [newAlias, setNewAlias] = useState('')
  const [aliasDeleteId, setAliasDeleteId] = useState<number | null>(null)

  const { data, isLoading, isError } = useQuery<ContactDetail>({
    queryKey: ['contact-detail', contactId],
    queryFn: () => api.get(`/contacts/${contactId}/detail`).then((r) => r.data),
    enabled: Number.isFinite(contactId),
  })

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['contact-detail', contactId] })

  const addAlias = useMutation({
    mutationFn: () =>
      api.post('/aliases/', {
        alias: newAlias.trim(),
        contact_id: contactId,
        confidence: 1.0,
      }),
    onSuccess: () => {
      setNewAlias('')
      invalidate()
      queryClient.invalidateQueries({ queryKey: ['aliases'] })
    },
  })

  const deleteAlias = useMutation({
    mutationFn: (aliasId: number) => api.delete(`/aliases/${aliasId}`),
    onSuccess: () => {
      setAliasDeleteId(null)
      invalidate()
      queryClient.invalidateQueries({ queryKey: ['aliases'] })
    },
  })

  if (!Number.isFinite(contactId)) {
    return <div className="p-6 text-sm text-muted-foreground">Invalid contact id.</div>
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="p-6 space-y-3">
        <Button variant="ghost" size="sm" onClick={() => navigate('/contacts')}>
          <ArrowLeft className="w-3.5 h-3.5 mr-1.5" />
          Back to Contacts
        </Button>
        <p className="text-sm text-muted-foreground">Contact not found.</p>
      </div>
    )
  }

  const { contact, invoices, bills, aliases } = data
  const canAdd = newAlias.trim().length > 0 && !addAlias.isPending

  return (
    <div className="space-y-5">
      {/* Back nav */}
      <Button
        variant="ghost"
        size="sm"
        className="-ml-2 text-muted-foreground hover:text-foreground"
        onClick={() => navigate('/contacts')}
      >
        <ArrowLeft className="w-3.5 h-3.5 mr-1.5" />
        Back to Contacts
      </Button>

      {/* Header card */}
      <Card>
        <CardContent className="py-5 px-5">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <h1 className="text-xl font-bold">{contact.full_name}</h1>
              <div className="flex items-center gap-2 mt-1.5">
                <Badge variant={TYPE_VARIANT[contact.contact_type] ?? 'muted'}>
                  {contact.contact_type}
                </Badge>
                {contact.company && (
                  <span className="text-sm text-muted-foreground">{contact.company}</span>
                )}
              </div>
            </div>
            <div className="text-xs text-muted-foreground space-y-0.5 text-right">
              {contact.email && <div>{contact.email}</div>}
              {contact.phone && <div>{contact.phone}</div>}
              {contact.address && <div>{contact.address}</div>}
            </div>
          </div>
          {contact.notes && (
            <div className="mt-3 pt-3 border-t text-xs text-muted-foreground">
              {contact.notes}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Aliases section */}
      <section className="space-y-2">
        <div>
          <h2 className="text-sm font-semibold">Aliases</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Raw bank-statement strings that should resolve to{' '}
            <span className="font-medium text-foreground">{contact.full_name}</span>.
          </p>
        </div>

        <Card>
          <CardContent className="py-4 px-4 space-y-3">
            <div className="flex items-center gap-2 flex-wrap">
              <Input
                className="flex-1 min-w-[180px]"
                placeholder="Raw bank text (e.g. AMZN MKTP)"
                value={newAlias}
                onChange={(e) => setNewAlias(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && canAdd && addAlias.mutate()}
              />
              <Button
                size="sm"
                onClick={() => addAlias.mutate()}
                disabled={!canAdd}
                className="flex-shrink-0"
              >
                <Plus className="w-3.5 h-3.5 mr-1.5" />
                Add Alias
              </Button>
            </div>

            {aliases.length === 0 ? (
              <p className="text-xs text-muted-foreground py-2">
                No aliases yet. Aliases let the matcher recognise messy bank descriptions
                as this contact.
              </p>
            ) : (
              <div className="divide-y -mx-4">
                {aliases.map((a) => (
                  <div
                    key={a.id}
                    className="flex items-center justify-between gap-3 px-4 py-2.5"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="font-mono text-xs truncate">{a.alias}</span>
                      <Badge variant={a.source === 'human' ? 'info' : 'muted'}>
                        {a.source}
                      </Badge>
                      <span className="text-xs text-muted-foreground whitespace-nowrap">
                        {(a.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                    {aliasDeleteId === a.id ? (
                      <div className="inline-flex items-center gap-1.5 flex-shrink-0">
                        <span className="text-xs text-muted-foreground">Delete?</span>
                        <Button
                          size="sm"
                          variant="destructive"
                          className="h-6 px-2 text-xs"
                          onClick={() => deleteAlias.mutate(a.id)}
                          disabled={deleteAlias.isPending}
                        >
                          Yes
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-6 px-2 text-xs"
                          onClick={() => setAliasDeleteId(null)}
                        >
                          No
                        </Button>
                      </div>
                    ) : (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 w-7 p-0 text-destructive hover:text-destructive flex-shrink-0"
                        onClick={() => setAliasDeleteId(a.id)}
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </section>

      {/* Documents — two columns */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <DocList
          title="Invoices"
          emptyMsg="No invoices linked to this contact yet."
          rows={invoices}
          linkPrefix="/sales"
        />
        <DocList
          title="Bills"
          emptyMsg="No bills linked to this contact yet."
          rows={bills}
          linkPrefix="/purchases"
        />
      </div>
    </div>
  )
}

function DocList({
  title,
  emptyMsg,
  rows,
  linkPrefix,
}: {
  title: string
  emptyMsg: string
  rows: ContactDetail['invoices']
  linkPrefix: string
}) {
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold">{title}</h2>
      <Card>
        <CardContent className="p-0">
          {rows.length === 0 ? (
            <p className="text-xs text-muted-foreground py-6 text-center">{emptyMsg}</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/40">
                  <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">
                    #
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-muted-foreground">
                    Date
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-semibold text-muted-foreground">
                    Total
                  </th>
                  <th className="px-3 py-2 text-right text-xs font-semibold text-muted-foreground">
                    Outstanding
                  </th>
                  <th className="px-3 py-2 text-center text-xs font-semibold text-muted-foreground">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.id}
                    className={cn(
                      'border-b last:border-0 hover:bg-muted/30 transition-colors',
                    )}
                  >
                    <td className="px-3 py-2 font-mono text-xs">
                      <Link
                        to={linkPrefix}
                        className="text-primary hover:underline"
                      >
                        {row.number ?? `#${row.id}`}
                      </Link>
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {formatDate(row.issue_date)}
                    </td>
                    <td className="px-3 py-2 text-right text-xs">
                      {formatCurrency(row.total, row.currency)}
                    </td>
                    <td className="px-3 py-2 text-right text-xs font-medium">
                      {formatCurrency(row.outstanding, row.currency)}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <Badge variant={STATUS_VARIANT[row.status] ?? 'muted'}>
                        {STATUS_LABEL[row.status] ?? row.status}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </section>
  )
}
