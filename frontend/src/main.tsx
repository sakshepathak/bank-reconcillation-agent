import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfirmProvider } from '@/components/ConfirmProvider'
import { ToastProvider } from '@/components/ToastProvider'
import { ThemeProvider, applyTheme, resolveTheme, readStoredChoice } from '@/lib/theme-context'
import App from './App'
import './index.css'

// Apply the saved theme class before first paint, so there's no light→dark flash.
applyTheme(resolveTheme(readStoredChoice()))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <ConfirmProvider>
            <App />
          </ConfirmProvider>
        </ToastProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
