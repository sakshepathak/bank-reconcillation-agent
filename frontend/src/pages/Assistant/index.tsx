import { useState, useRef, useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Sparkles, Send, Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

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
  'What does my business do?',
]

export default function Assistant() {
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  const send = useMutation({
    mutationFn: (text: string) =>
      api
        .post<ChatResponse>('/chat/', { message: text, history: messages })
        .then((r) => r.data),
    onSuccess: (data) => {
      setMessages((m) => [...m, { role: 'assistant', content: data.reply }])
    },
    onError: () => {
      setMessages((m) => [
        ...m,
        { role: 'assistant', content: "Sorry — I couldn't reach the assistant just now. Please try again." },
      ])
    },
  })

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, send.isPending])

  function submit(text: string) {
    const trimmed = text.trim()
    if (!trimmed || send.isPending) return
    setMessages((m) => [...m, { role: 'user', content: trimmed }])
    setInput('')
    send.mutate(trimmed)
  }

  const empty = messages.length === 0

  return (
    <div className="flex flex-col h-[calc(100vh-7rem)] animate-in fade-in-0 duration-300">
      {/* Header */}
      <div className="flex items-center gap-3 pb-4">
        <div className="w-10 h-10 rounded-xl bg-primary-subtle text-primary flex items-center justify-center">
          <Sparkles className="w-5 h-5" />
        </div>
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-foreground">Assistant</h1>
          <p className="text-sm text-muted-foreground">
            Ask about your invoices, bills, balances and contacts — answers come straight from your books.
          </p>
        </div>
      </div>

      {/* Conversation */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto rounded-xl border bg-card shadow-sm p-5 space-y-4"
      >
        {empty ? (
          <div className="h-full flex flex-col items-center justify-center text-center">
            <div className="w-12 h-12 rounded-2xl bg-primary-subtle text-primary flex items-center justify-center mb-3">
              <Sparkles className="w-6 h-6" />
            </div>
            <p className="text-foreground font-medium">How can I help with your books?</p>
            <p className="text-sm text-muted-foreground mt-1 mb-5 max-w-sm">
              I read your live data — try one of these to get started.
            </p>
            <div className="flex flex-wrap gap-2 justify-center max-w-lg">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => submit(s)}
                  className="text-sm px-3.5 py-2 rounded-full border bg-background hover:bg-muted text-foreground transition-colors"
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
                  'max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap',
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
            <div className="bg-muted text-muted-foreground rounded-2xl rounded-bl-md px-4 py-3 flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span className="text-sm">Looking that up…</span>
            </div>
          </div>
        )}
      </div>

      {/* Composer */}
      <form
        onSubmit={(e) => { e.preventDefault(); submit(input) }}
        className="mt-4 flex items-center gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about your invoices, bills or balances…"
          className="flex-1 h-11 rounded-xl border border-input bg-card px-4 text-sm text-foreground placeholder:text-muted-foreground shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        />
        <button
          type="submit"
          disabled={!input.trim() || send.isPending}
          className="h-11 w-11 flex items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm hover:bg-primary-hover active:scale-95 transition-all disabled:opacity-50 disabled:pointer-events-none"
        >
          <Send className="w-4 h-4" />
        </button>
      </form>
      <p className="text-[11px] text-muted-foreground text-center mt-2">
        The assistant only sees this organisation's data and reads exact figures from your records.
      </p>
    </div>
  )
}
