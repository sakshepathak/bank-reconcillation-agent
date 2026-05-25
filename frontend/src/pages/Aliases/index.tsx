import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate } from '@/lib/utils'
import type { VendorAlias } from '@/types'

export default function Aliases() {
  const queryClient = useQueryClient()
  const [alias, setAlias] = useState('')
  const [canonical, setCanonical] = useState('')
  const [deleteId, setDeleteId] = useState<number | null>(null)

  const { data: aliases, isLoading } = useQuery<VendorAlias[]>({
    queryKey: ['aliases'],
    queryFn: () => api.get('/aliases/').then((r) => r.data),
  })

  const createMutation = useMutation({
    mutationFn: () => api.post('/aliases/', { alias, canonical_name: canonical, confidence: 1.0 }),
    onSuccess: () => {
      setAlias('')
      setCanonical('')
      queryClient.invalidateQueries({ queryKey: ['aliases'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/aliases/${id}`),
    onSuccess: () => {
      setDeleteId(null)
      queryClient.invalidateQueries({ queryKey: ['aliases'] })
    },
  })

  const canAdd = alias.trim() && canonical.trim()

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold">Vendor Aliases</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Map raw bank descriptions to canonical vendor names for accurate matching.
        </p>
      </div>

      {/* Add form */}
      <Card>
        <CardContent className="py-4 px-4">
          <p className="text-xs font-semibold text-muted-foreground mb-3">Add Alias</p>
          <div className="flex items-center gap-2 flex-wrap">
            <Input
              className="flex-1 min-w-[140px]"
              placeholder="Raw bank text (e.g. AMZN MKTP)"
              value={alias}
              onChange={(e) => setAlias(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && canAdd && createMutation.mutate()}
            />
            <span className="text-muted-foreground text-sm flex-shrink-0">→</span>
            <Input
              className="flex-1 min-w-[140px]"
              placeholder="Canonical name (e.g. Amazon)"
              value={canonical}
              onChange={(e) => setCanonical(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && canAdd && createMutation.mutate()}
            />
            <Button
              size="sm"
              onClick={() => createMutation.mutate()}
              disabled={!canAdd || createMutation.isPending}
              className="flex-shrink-0"
            >
              <Plus className="w-3.5 h-3.5 mr-1.5" />
              Add
            </Button>
          </div>
          <p className="text-xs text-muted-foreground mt-2">
            Raw text is lowercased automatically. Use exact substrings the bank uses.
          </p>
        </CardContent>
      </Card>

      {/* Table */}
      <Card>
        <CardContent className="p-0 overflow-x-auto">
          {isLoading ? (
            <div className="p-4 space-y-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : !aliases?.length ? (
            <div className="py-12 text-center text-sm text-muted-foreground">
              No aliases yet. Add one above to improve name matching accuracy.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/40">
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">
                    Raw bank text
                  </th>
                  <th className="px-4 py-2.5 text-left text-xs font-semibold text-muted-foreground">
                    Canonical name
                  </th>
                  <th className="px-4 py-2.5 text-center text-xs font-semibold text-muted-foreground">
                    Confidence
                  </th>
                  <th className="px-4 py-2.5 text-center text-xs font-semibold text-muted-foreground">
                    Source
                  </th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold text-muted-foreground">
                    Added
                  </th>
                  <th className="px-4 py-2.5 text-right text-xs font-semibold text-muted-foreground">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody>
                {aliases.map((a) => (
                  <tr key={a.id} className="border-b last:border-0 hover:bg-muted/30 transition-colors">
                    <td className="px-4 py-2.5 font-mono text-xs">{a.alias}</td>
                    <td className="px-4 py-2.5 font-medium">{a.canonical_name}</td>
                    <td className="px-4 py-2.5 text-center font-mono text-xs">
                      {(a.confidence * 100).toFixed(0)}%
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      <Badge variant={a.source === 'human' ? 'info' : 'muted'}>
                        {a.source}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 text-right text-xs text-muted-foreground whitespace-nowrap">
                      {formatDate(a.created_at)}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      {deleteId === a.id ? (
                        <div className="inline-flex items-center gap-1.5">
                          <span className="text-xs text-muted-foreground">Delete?</span>
                          <Button
                            size="sm"
                            variant="destructive"
                            className="h-6 px-2 text-xs"
                            onClick={() => deleteMutation.mutate(a.id)}
                            disabled={deleteMutation.isPending}
                          >
                            Yes
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-6 px-2 text-xs"
                            onClick={() => setDeleteId(null)}
                          >
                            No
                          </Button>
                        </div>
                      ) : (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                          onClick={() => setDeleteId(a.id)}
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
    </div>
  )
}
