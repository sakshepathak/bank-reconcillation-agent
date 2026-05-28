/**
 * Persistent upload dock — bottom-right of the screen, shows every file in
 * the current upload session with its live status. Replaces both the
 * floating toast AND the separate "failed uploads" card so the user has
 * one place to look.
 *
 * Behavior:
 *   - Visible whenever there's at least one item to show
 *   - Per-file status: queued / uploading / done / failed
 *   - Successful items auto-dismiss after a short delay IF nothing failed
 *   - Failed items stay until manually retried or dismissed
 *   - Collapsible (click chevron) and dismissable (click X to clear all)
 */
import { useState } from 'react'
import {
  ChevronDown, ChevronUp, X, Check, AlertCircle, Loader2, RefreshCw, Circle,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export interface UploadItem {
  id: string
  file: File
  filename: string
  status: 'queued' | 'uploading' | 'done' | 'failed'
  error?: string
  retryCount: number
}

export function UploadDock({
  items,
  onRetry,
  onRetryAll,
  onDismiss,
  onDismissAll,
}: {
  items: UploadItem[]
  onRetry: (item: UploadItem) => void
  onRetryAll: () => void
  onDismiss: (id: string) => void
  onDismissAll: () => void
}) {
  const [collapsed, setCollapsed] = useState(false)

  if (items.length === 0) return null

  const stats = {
    total: items.length,
    done: items.filter((i) => i.status === 'done').length,
    uploading: items.filter((i) => i.status === 'uploading').length,
    queued: items.filter((i) => i.status === 'queued').length,
    failed: items.filter((i) => i.status === 'failed').length,
  }
  const inProgress = stats.uploading + stats.queued > 0
  const allDone = !inProgress

  return (
    <div className="fixed bottom-4 right-4 z-50 w-[400px] max-w-[calc(100vw-2rem)] bg-background rounded-lg border shadow-xl overflow-hidden">
      {/* Header */}
      <div className="px-3 py-2 flex items-center justify-between gap-2 bg-muted/40 border-b">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {inProgress ? (
            <Loader2 className="w-4 h-4 animate-spin text-primary flex-shrink-0" />
          ) : stats.failed > 0 ? (
            <AlertCircle className="w-4 h-4 text-amber-600 flex-shrink-0" />
          ) : (
            <Check className="w-4 h-4 text-emerald-600 flex-shrink-0" />
          )}
          <p className="text-sm font-medium truncate">
            {inProgress
              ? `Uploading ${stats.done + stats.uploading + 1 > stats.total ? stats.total : stats.done + stats.uploading} of ${stats.total}`
              : stats.failed > 0
                ? `${stats.done} done · ${stats.failed} failed`
                : `${stats.done} uploaded`}
          </p>
        </div>
        <div className="flex items-center gap-0.5 flex-shrink-0">
          {stats.failed > 0 && allDone && (
            <Button
              size="sm"
              variant="ghost"
              className="h-6 px-2 text-xs"
              onClick={onRetryAll}
            >
              <RefreshCw className="w-3 h-3 mr-1" />
              Retry all
            </Button>
          )}
          <button
            onClick={() => setCollapsed((c) => !c)}
            className="p-1 text-muted-foreground hover:text-foreground rounded hover:bg-muted"
            title={collapsed ? 'Expand' : 'Collapse'}
          >
            {collapsed ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
          <button
            onClick={onDismissAll}
            className="p-1 text-muted-foreground hover:text-foreground rounded hover:bg-muted"
            title="Clear all"
            disabled={inProgress}
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Progress bar */}
      {inProgress && (
        <div className="h-0.5 bg-muted">
          <div
            className="h-full bg-primary transition-all duration-300"
            style={{ width: `${((stats.done + stats.failed) / stats.total) * 100}%` }}
          />
        </div>
      )}

      {/* Items */}
      {!collapsed && (
        <div className="max-h-[300px] overflow-y-auto">
          {items.map((item) => (
            <UploadRow key={item.id} item={item} onRetry={onRetry} onDismiss={onDismiss} />
          ))}
        </div>
      )}
    </div>
  )
}

function UploadRow({
  item, onRetry, onDismiss,
}: {
  item: UploadItem
  onRetry: (item: UploadItem) => void
  onDismiss: (id: string) => void
}) {
  return (
    <div
      className={cn(
        'flex items-center gap-2 px-3 py-2 border-b last:border-0 transition-colors',
        item.status === 'failed' && 'bg-amber-50/40',
        item.status === 'done' && 'bg-emerald-50/30',
      )}
    >
      <StatusIcon status={item.status} />
      <div className="min-w-0 flex-1">
        <p className="text-sm truncate font-medium">{item.filename}</p>
        {item.status === 'failed' && item.error && (
          <p className="text-[11px] text-amber-700 truncate leading-tight mt-0.5">
            {item.error}
            {item.retryCount > 0 && (
              <span className="text-muted-foreground"> · retried {item.retryCount}x</span>
            )}
          </p>
        )}
        {item.status === 'uploading' && (
          <p className="text-[11px] text-muted-foreground leading-tight mt-0.5">
            Reading and extracting…
          </p>
        )}
      </div>
      <div className="flex items-center gap-0.5 flex-shrink-0">
        {item.status === 'failed' && (
          <Button
            size="sm"
            variant="ghost"
            className="h-7 w-7 p-0"
            onClick={() => onRetry(item)}
            title="Retry"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </Button>
        )}
        {(item.status === 'done' || item.status === 'failed') && (
          <Button
            size="sm"
            variant="ghost"
            className="h-7 w-7 p-0 text-muted-foreground"
            onClick={() => onDismiss(item.id)}
            title="Dismiss"
          >
            <X className="w-3.5 h-3.5" />
          </Button>
        )}
      </div>
    </div>
  )
}

function StatusIcon({ status }: { status: UploadItem['status'] }) {
  if (status === 'done') {
    return <Check className="w-4 h-4 text-emerald-600 flex-shrink-0" />
  }
  if (status === 'failed') {
    return <AlertCircle className="w-4 h-4 text-amber-600 flex-shrink-0" />
  }
  if (status === 'uploading') {
    return <Loader2 className="w-4 h-4 text-primary animate-spin flex-shrink-0" />
  }
  return <Circle className="w-4 h-4 text-muted-foreground/50 flex-shrink-0" />
}
