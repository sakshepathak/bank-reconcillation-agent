import { useState, useRef, useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Send, X } from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import MatchaMark from '@/components/MatchaMark'
import MatchaCup from '@/components/MatchaCup'
import MatchaCupLoader from '@/components/MatchaCupLoader'

/** Three little rising steam wisps. `tone` lets it sit on dark or light. */
function Steam({ tone = 'light', className }: { tone?: 'light' | 'matcha'; className?: string }) {
  return (
    <span className={cn('pointer-events-none flex gap-1', className)} aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className={cn('block w-[3px] h-3 rounded-full animate-steam', tone === 'light' ? 'bg-white/70' : 'bg-primary/40')}
          style={{ animationDelay: `${i * 0.5}s` }}
        />
      ))}
    </span>
  )
}

/**
 * Matcha — the floating assistant. A circular bubble pinned bottom-right that
 * expands into a chat card. It talks to the very same POST /chat/ endpoint the
 * full Assistant page uses (same payload, same org-scoped, read-only tools), so
 * this is purely an additional surface — it adds no new logic and the
 * /assistant page keeps working untouched. Conversation state lives here and
 * survives route changes because the widget is mounted in AppShell, which does
 * not remount as you navigate between pages.
 */

interface Msg {
  role: 'user' | 'assistant'
  content: string
}

interface ChatResponse {
  reply: string
  tools_used: string[]
}

const SUGGESTIONS = [
  "What's my total outstanding?",
  'Who owes me the most?',
  'What invoices are overdue?',
]

export default function MatchaChat() {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const send = useMutation({
    mutationFn: (text: string) =>
      api.post<ChatResponse>('/chat/', { message: text, history: messages }).then((r) => r.data),
    onSuccess: (data) => {
      setMessages((m) => [...m, { role: 'assistant', content: data.reply }])
    },
    onError: () => {
      setMessages((m) => [
        ...m,
        { role: 'assistant', content: "Sorry — I couldn't reach the kitchen just now. Give it another whisk in a moment. 🍵" },
      ])
    },
  })

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, send.isPending])

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 80)
  }, [open])

  function submit(text: string) {
    const trimmed = text.trim()
    if (!trimmed || send.isPending) return
    setMessages((m) => [...m, { role: 'user', content: trimmed }])
    setInput('')
    send.mutate(trimmed)
  }

  const empty = messages.length === 0

  return (
    <>
      {/* Expanded card */}
      {open && (
        <div
          className={cn(
            'fixed bottom-24 right-6 z-50 flex flex-col overflow-hidden',
            'w-[min(23rem,calc(100vw-3rem))] h-[min(34rem,calc(100vh-9rem))]',
            'rounded-2xl border bg-card shadow-lg',
            'animate-in fade-in-0 zoom-in-95 slide-in-from-bottom-2 duration-200 origin-bottom-right',
          )}
          role="dialog"
          aria-label="Matcha assistant"
        >
          {/* Header */}
          <div className="relative overflow-hidden flex items-center gap-3 px-4 py-3.5 bg-gradient-to-br from-[hsl(84_45%_40%)] via-primary to-[hsl(89_52%_22%)] text-primary-foreground">
            <MatchaMark className="absolute -right-3 -bottom-5 w-24 h-24 text-white/10 animate-sway" />
            <div className="relative w-10 h-10 rounded-2xl bg-white/15 flex items-center justify-center flex-shrink-0">
              <MatchaCup className="w-7 h-7" />
            </div>
            <div className="relative min-w-0 flex-1">
              <p className="font-display font-semibold leading-tight text-[17px]">Matcha</p>
              <p className="text-[11px] text-white/75 leading-tight">your books, freshly whisked</p>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="relative rounded-lg p-1.5 text-white/75 hover:text-white hover:bg-white/15 transition-colors"
              aria-label="Close"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Conversation */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
            {empty ? (
              <div className="h-full flex flex-col items-center justify-center text-center px-2">
                <div className="relative mb-3">
                  <Steam tone="matcha" className="absolute -top-2.5 left-1/2 -translate-x-1/2" />
                  <div className="w-14 h-14 rounded-2xl bg-primary-subtle flex items-center justify-center animate-bob">
                    <MatchaCup className="w-9 h-9" />
                  </div>
                </div>
                <p className="text-foreground font-medium">Matcha here. 🍵</p>
                <p className="text-sm text-muted-foreground mt-1 mb-4">
                  I match your bank lines to invoices and bills — ask me anything from your books.
                </p>
                <div className="flex flex-col gap-2 w-full">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => submit(s)}
                      className="text-sm px-3.5 py-2 rounded-xl border bg-background hover:bg-muted text-foreground text-left transition-colors"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((m, i) => (
                <div key={i} className={cn('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}>
                  <div
                    className={cn(
                      'max-w-[85%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed whitespace-pre-wrap',
                      m.role === 'user'
                        ? 'bg-primary text-primary-foreground rounded-br-md'
                        : 'bg-muted text-foreground rounded-bl-md',
                    )}
                  >
                    {m.content}
                  </div>
                </div>
              ))
            )}

            {send.isPending && (
              <div className="flex justify-start">
                <div className="bg-muted text-muted-foreground rounded-2xl rounded-bl-md pl-2 pr-3.5 py-1.5 flex items-center gap-1.5">
                  <MatchaCupLoader className="w-7 h-7" />
                  <span className="text-sm">Whisking that up…</span>
                </div>
              </div>
            )}
          </div>

          {/* Composer */}
          <form
            onSubmit={(e) => { e.preventDefault(); submit(input) }}
            className="flex items-center gap-2 p-3 border-t bg-card"
          >
            <input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask Matcha…"
              className="flex-1 h-10 rounded-xl border border-input bg-background px-3.5 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <button
              type="submit"
              disabled={!input.trim() || send.isPending}
              className="h-10 w-10 flex items-center justify-center rounded-xl bg-primary text-primary-foreground hover:bg-primary-hover active:scale-95 transition-all disabled:opacity-50 disabled:pointer-events-none"
              aria-label="Send"
            >
              <Send className="w-4 h-4" />
            </button>
          </form>
        </div>
      )}

      {/* The bubble — a steaming cup of matcha */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={open ? 'Close Matcha assistant' : 'Open Matcha assistant'}
        className={cn(
          'group fixed bottom-6 right-6 z-50 w-16 h-16 rounded-full shadow-lg',
          'flex items-center justify-center overflow-visible',
          'bg-gradient-to-br from-[hsl(84_46%_46%)] via-primary to-[hsl(89_52%_22%)]',
          'ring-1 ring-black/5 hover:ring-4 hover:ring-primary/25',
          'hover:scale-105 active:scale-95 transition-[transform,box-shadow] duration-150',
          !open && 'animate-bob',
        )}
      >
        {/* steam rising off the cup while it's resting */}
        {!open && <Steam className="absolute -top-1 left-1/2 -translate-x-1/2" />}
        {open
          ? <X className="w-6 h-6 text-white" />
          : <MatchaCup className="w-9 h-9 drop-shadow-sm group-hover-wiggle" />}
      </button>
    </>
  )
}
