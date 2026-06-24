/**
 * ConfirmProvider — app-wide async confirmation dialog.
 *
 * Replaces native window.confirm() with a styled, awaitable modal. Any component
 * under <ConfirmProvider> calls the hook and awaits a boolean:
 *
 *     const confirm = useConfirm()
 *     const ok = await confirm({ title: 'Delete this?', destructive: true })
 *     if (ok) { ... }
 *
 * Options:
 *   title         — heading (required)
 *   description   — supporting text
 *   confirmText   — confirm button label (default "Confirm")
 *   cancelText    — cancel button label  (default "Cancel")
 *   destructive   — style the confirm button red (for deletes)
 *   rememberKey   — localStorage key for a "Don't ask again" preference
 *   persistChoice — show the "Don't ask again" checkbox; when ticked, the chosen
 *                   Yes/No is saved under rememberKey and future calls with that
 *                   key resolve immediately without showing the dialog.
 *
 * Deliberately self-contained (plain overlay, no extra dialog dependency) so it
 * can never break the build over a primitive's API.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react'
import { Button } from '@/components/ui/button'

export interface ConfirmOptions {
  title: string
  description?: string
  confirmText?: string
  cancelText?: string
  destructive?: boolean
  rememberKey?: string
  persistChoice?: boolean
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>

const ConfirmContext = createContext<ConfirmFn | null>(null)

const STORAGE_PREFIX = 'confirm-pref:'

function readPref(key?: string): boolean | null {
  if (!key) return null
  try {
    const v = localStorage.getItem(STORAGE_PREFIX + key)
    return v === null ? null : v === 'true'
  } catch {
    return null
  }
}

function writePref(key: string, value: boolean): void {
  try {
    localStorage.setItem(STORAGE_PREFIX + key, String(value))
  } catch {
    /* ignore quota / private-mode errors */
  }
}

interface PendingState extends ConfirmOptions {
  resolve: (value: boolean) => void
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<PendingState | null>(null)
  const [dontAsk, setDontAsk] = useState(false)

  const confirm = useCallback<ConfirmFn>((options) => {
    // Honour a previously-saved "Don't ask again" choice — skip the dialog.
    const remembered = readPref(options.rememberKey)
    if (remembered !== null) return Promise.resolve(remembered)
    setDontAsk(false)
    return new Promise<boolean>((resolve) => {
      setPending({ ...options, resolve })
    })
  }, [])

  const settle = useCallback(
    (result: boolean) => {
      setPending((p) => {
        if (p) {
          if (p.persistChoice && p.rememberKey && dontAsk) writePref(p.rememberKey, result)
          p.resolve(result)
        }
        return null
      })
    },
    [dontAsk],
  )

  // Escape cancels the dialog.
  useEffect(() => {
    if (!pending) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') settle(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pending, settle])

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => settle(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            className="w-full max-w-md rounded-lg border border-border bg-background p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-base font-semibold text-foreground">{pending.title}</h2>
            {pending.description && (
              <p className="mt-2 text-sm text-muted-foreground">{pending.description}</p>
            )}

            {pending.persistChoice && pending.rememberKey && (
              <label className="mt-3 flex items-center gap-2 select-none text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={dontAsk}
                  onChange={(e) => setDontAsk(e.target.checked)}
                  className="h-3.5 w-3.5 rounded border-input"
                />
                {"Don't ask again"}
              </label>
            )}

            <div className="mt-5 flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => settle(false)}>
                {pending.cancelText ?? 'Cancel'}
              </Button>
              <Button
                variant={pending.destructive ? 'destructive' : 'default'}
                size="sm"
                autoFocus
                onClick={() => settle(true)}
              >
                {pending.confirmText ?? 'Confirm'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  )
}

export function useConfirm(): ConfirmFn {
  const ctx = useContext(ConfirmContext)
  if (!ctx) throw new Error('useConfirm must be used within <ConfirmProvider>')
  return ctx
}
