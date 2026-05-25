import { useQuery } from '@tanstack/react-query'
import { RefreshCw, Users, TrendingUp, Clock, AlertCircle } from 'lucide-react'
import { api } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate, formatPct } from '@/lib/utils'
import type { DashboardStats, RunSummary } from '@/types'

function StatCard({
  title, value, sub, icon: Icon, accent = false,
}: {
  title: string
  value: string | number
  sub?: string
  icon: React.ElementType
  accent?: boolean
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle>{title}</CardTitle>
          <div className={`p-2 rounded-lg ${accent ? 'bg-primary/10' : 'bg-muted'}`}>
            <Icon className={`w-4 h-4 ${accent ? 'text-primary' : 'text-muted-foreground'}`} />
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-bold text-foreground">{value}</p>
        {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
      </CardContent>
    </Card>
  )
}

export default function Dashboard() {
  const { data: stats, isLoading: statsLoading } = useQuery<DashboardStats>({
    queryKey: ['dashboard', 'stats'],
    queryFn: () => api.get('/dashboard/stats').then((r) => r.data),
  })

  const { data: runs, isLoading: runsLoading } = useQuery<RunSummary[]>({
    queryKey: ['runs'],
    queryFn: () => api.get('/runs/').then((r) => r.data),
  })

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-foreground">Dashboard</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Overview of your reconciliation activity
        </p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {statsLoading ? (
          Array.from({ length: 4 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="pt-5">
                <Skeleton className="h-4 w-24 mb-3" />
                <Skeleton className="h-8 w-16" />
              </CardContent>
            </Card>
          ))
        ) : stats ? (
          <>
            <StatCard
              title="Total Runs"
              value={stats.total_runs}
              sub={stats.last_run_date ? `Last: ${formatDate(stats.last_run_date)}` : 'No runs yet'}
              icon={RefreshCw}
              accent
            />
            <StatCard
              title="Match Rate"
              value={formatPct(stats.overall_match_rate)}
              sub={`${stats.total_transactions} transactions`}
              icon={TrendingUp}
              accent
            />
            <StatCard
              title="Pending Review"
              value={stats.pending_review}
              sub="items need attention"
              icon={AlertCircle}
            />
            <StatCard
              title="Contacts"
              value={stats.total_contacts}
              sub="customers & suppliers"
              icon={Users}
            />
          </>
        ) : null}
      </div>

      {/* Recent Runs */}
      <div>
        <h2 className="text-sm font-semibold text-foreground mb-3">Recent Runs</h2>
        {runsLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : !runs?.length ? (
          <Card>
            <CardContent className="py-10 text-center">
              <RefreshCw className="w-8 h-8 text-muted-foreground mx-auto mb-2 opacity-40" />
              <p className="text-sm text-muted-foreground">
                No reconciliation runs yet. Upload a bank statement to get started.
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-2">
            {runs.slice(0, 8).map((run) => (
              <Card key={run.run_id}>
                <CardContent className="py-3 px-4">
                  <div className="flex items-center justify-between gap-4">
                    <div className="min-w-0">
                      <p className="font-mono text-xs text-muted-foreground truncate">
                        {run.run_id}
                      </p>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {formatDate(run.created_at)} · {run.total} transactions
                      </p>
                    </div>
                    <div className="flex items-center gap-3 flex-shrink-0">
                      {run.pending > 0 && (
                        <div className="flex items-center gap-1 text-amber-600">
                          <Clock className="w-3 h-3" />
                          <span className="text-xs font-medium">{run.pending} pending</span>
                        </div>
                      )}
                      <div className="text-right">
                        <p className="text-sm font-bold text-foreground">
                          {formatPct(run.match_rate)}
                        </p>
                        <p className="text-xs text-muted-foreground">matched</p>
                      </div>
                      {/* Match rate bar */}
                      <div className="w-20 h-1.5 bg-muted rounded-full overflow-hidden">
                        <div
                          className="h-full bg-primary rounded-full transition-all"
                          style={{ width: `${run.match_rate}%` }}
                        />
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
