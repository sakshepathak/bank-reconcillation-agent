import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Upload, FileText, RefreshCw, ExternalLink } from 'lucide-react'
import { api } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn, formatDate, formatPct } from '@/lib/utils'
import type { RunSummary } from '@/types'

const ACCEPTED = '.csv,.xlsx,.xls,.ofx,.qif'

export default function Reconciliation() {
  const fileRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: runs, isLoading } = useQuery<RunSummary[]>({
    queryKey: ['runs'],
    queryFn: () => api.get('/runs/').then((r) => r.data),
  })

  const handleFile = (f: File) => {
    setFile(f)
    setError(null)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) handleFile(f)
  }

  const handleUpload = async () => {
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      await api.post('/runs/upload', form, { headers: { 'Content-Type': 'multipart/form-data' } })
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      if (msg.includes('501') || msg.toLowerCase().includes('not implemented')) {
        setError(
          'Upload via React UI is not yet available. Use Streamlit on :8501 to run reconciliation, then come back here to review results.',
        )
      } else {
        setError(msg)
      }
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold">Reconciliation</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Upload bank statements to run the matching engine.
        </p>
      </div>

      {/* Upload card */}
      <Card>
        <CardContent className="py-6 px-6 space-y-4">
          {/* Drop zone */}
          <div
            className={cn(
              'border-2 border-dashed rounded-lg p-10 text-center transition-colors cursor-pointer',
              dragging ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/50 hover:bg-muted/30',
              file && 'border-emerald-300 bg-emerald-50/40',
            )}
            onClick={() => fileRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
          >
            {file ? (
              <div className="flex flex-col items-center gap-2">
                <FileText className="w-8 h-8 text-emerald-600" />
                <p className="font-medium text-sm">{file.name}</p>
                <p className="text-xs text-muted-foreground">
                  {(file.size / 1024).toFixed(1)} KB · Click to change
                </p>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2">
                <Upload className="w-8 h-8 text-muted-foreground opacity-50" />
                <p className="text-sm font-medium text-foreground">
                  Drop your bank statement here
                </p>
                <p className="text-xs text-muted-foreground">or click to browse</p>
                <div className="flex items-center gap-1.5 mt-2 flex-wrap justify-center">
                  {['CSV', 'XLSX', 'OFX', 'QIF'].map((ext) => (
                    <Badge key={ext} variant="muted">{ext}</Badge>
                  ))}
                </div>
              </div>
            )}
          </div>

          <input
            ref={fileRef}
            type="file"
            accept={ACCEPTED}
            className="hidden"
            onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
          />

          {/* Error / notice */}
          {error && (
            <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800 flex items-start gap-2">
              <span className="flex-1">{error}</span>
              <a
                href="http://localhost:8501"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 text-amber-700 font-medium hover:underline flex-shrink-0"
              >
                Open Streamlit <ExternalLink className="w-3 h-3" />
              </a>
            </div>
          )}

          <div className="flex items-center gap-3">
            <Button
              onClick={handleUpload}
              disabled={!file || uploading}
              className="w-full sm:w-auto"
            >
              {uploading ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                  Running…
                </>
              ) : (
                <>
                  <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
                  Run Reconciliation
                </>
              )}
            </Button>
            {file && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => { setFile(null); setError(null) }}
              >
                Clear
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Recent runs */}
      <div>
        <h2 className="text-sm font-semibold mb-3">Recent Runs</h2>
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-16 w-full" />
            ))}
          </div>
        ) : !runs?.length ? (
          <Card>
            <CardContent className="py-8 text-center">
              <p className="text-sm text-muted-foreground">
                No runs yet. Upload a statement above to get started.
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-2">
            {runs.map((run) => (
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
                    <div className="flex items-center gap-4 flex-shrink-0">
                      <div className="flex items-center gap-3 text-xs text-muted-foreground">
                        <span className="text-emerald-600 font-medium">{run.matched} matched</span>
                        {run.pending > 0 && (
                          <span className="text-amber-600 font-medium">{run.pending} pending</span>
                        )}
                        {run.unmatched > 0 && (
                          <span className="text-rose-600 font-medium">{run.unmatched} unmatched</span>
                        )}
                      </div>
                      <div className="text-right">
                        <p className="text-sm font-bold">{formatPct(run.match_rate)}</p>
                        <p className="text-xs text-muted-foreground">match rate</p>
                      </div>
                      <div className="w-16 h-1.5 bg-muted rounded-full overflow-hidden">
                        <div
                          className="h-full bg-primary rounded-full"
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
