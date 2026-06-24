/**
 * ToastProvider — lightweight, app-wide toast notifications.
 *
 * Any component under <ToastProvider> shows a transient message:
 *
 *     const toast = useToast()
 *     toast('Saved')                       // success (default)
 *     toast('Could not save', 'error')     // error
 *
 * Toasts auto-dismiss after a few seconds, or on click. Deliberately
 * self-contained (no extra toast dependency) so it can't break the build.
 */
import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from 'react'

type ToastVariant = 'success' | 'error'
type ToastFn = (message: string, variant?: ToastVariant) => void

interface ToastItem {
  id: number
  message: string
  variant: ToastVariant
}

const ToastContext = createContext<ToastFn | null>(null)

const DISMISS_MS = 4000

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const idRef = useRef(0)

  const remove = useCallback((id: number) => {
    setToasts((list) => list.filter((t) => t.id !== id))
  }, [])

  const toast = useCallback<ToastFn>(
    (message, variant = 'success') => {
      const id = ++idRef.current
      setToasts((list) => [...list, { id, message, variant }])
      window.setTimeout(() => remove(id), DISMISS_MS)
    },
    [remove],
  )

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="fixed bottom-4 right-4 z-[60] flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            onClick={() => remove(t.id)}
            className={
              'cursor-pointer rounded-md border px-4 py-3 text-sm shadow-lg ' +
              (t.variant === 'error'
                ? 'border-destructive/40 bg-destructive text-destructive-foreground'
                : 'border-border bg-background text-foreground')
            }
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastFn {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within <ToastProvider>')
  return ctx
}
