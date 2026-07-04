import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

/**
 * App-wide light/dark theme.
 *
 * The whole UI is built on semantic CSS-variable tokens (`--background`,
 * `--card`, `--primary`…), and Tailwind is configured with `darkMode: ['class']`.
 * So switching themes is just toggling a `dark` class on <html> — the `.dark`
 * block in index.css supplies the "Steeped" dark values and every token-based
 * surface re-skins at once. No per-component work.
 *
 * `choice` is what the user picked (persisted); `resolved` is what's actually
 * applied after resolving `system` against the OS preference.
 */

export type ThemeChoice = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

const STORAGE_KEY = 'matcha-theme'

type ThemeContextValue = {
  choice: ThemeChoice
  resolved: ResolvedTheme
  setChoice: (c: ThemeChoice) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function systemPrefersDark(): boolean {
  return typeof window !== 'undefined'
    && !!window.matchMedia
    && window.matchMedia('(prefers-color-scheme: dark)').matches
}

/** Read the saved choice. Defaults to `light` so existing users keep the warm
 *  paper look until they opt into dark or system. */
export function readStoredChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'light' || v === 'dark' || v === 'system') return v
  } catch { /* localStorage may be unavailable — fall through */ }
  return 'light'
}

export function resolveTheme(choice: ThemeChoice): ResolvedTheme {
  return choice === 'system' ? (systemPrefersDark() ? 'dark' : 'light') : choice
}

/** Toggle the `dark` class + native color-scheme on <html>. Exported so
 *  main.tsx can call it synchronously before first paint to avoid any flash. */
export function applyTheme(resolved: ResolvedTheme): void {
  const root = document.documentElement
  root.classList.toggle('dark', resolved === 'dark')
  root.style.colorScheme = resolved
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ThemeChoice>(readStoredChoice)
  const [resolved, setResolved] = useState<ResolvedTheme>(() => resolveTheme(choice))

  // Apply + persist whenever the choice changes.
  useEffect(() => {
    const r = resolveTheme(choice)
    setResolved(r)
    applyTheme(r)
    try { localStorage.setItem(STORAGE_KEY, choice) } catch { /* ignore */ }
  }, [choice])

  // While following the system, react to OS changes live.
  useEffect(() => {
    if (choice !== 'system' || !window.matchMedia) return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => {
      const r = resolveTheme('system')
      setResolved(r)
      applyTheme(r)
    }
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [choice])

  return (
    <ThemeContext.Provider value={{ choice, resolved, setChoice: setChoiceState }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within <ThemeProvider>')
  return ctx
}
