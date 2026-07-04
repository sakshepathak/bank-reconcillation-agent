import { NavLink } from 'react-router-dom'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  LayoutDashboard, RefreshCw, AlertTriangle, Receipt, FileSpreadsheet,
  Landmark, Users, FileText, BookOpen, Settings, LogOut, Sparkles, Workflow, Pin, PinOff,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { api } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import type { BankAccount } from '@/types'
import OrgSwitcher from '@/components/OrgSwitcher'
import MatchaMark from '@/components/MatchaMark'
import MatchaCup from '@/components/MatchaCup'
import { Leaf, Sparkle } from '@/components/Doodles'

type NavItem = { to: string; icon: typeof LayoutDashboard; label: string; badge?: boolean }

// Grouped nav — Work first (Reconcile at the very top with a pending badge),
// then Reference, then Admin.
const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: 'Work',
    items: [
      { to: '/reconciliation', icon: RefreshCw,       label: 'Reconcile', badge: true },
      { to: '/bank-accounts',  icon: Landmark,        label: 'Bank Accounts' },
      { to: '/sales',          icon: Receipt,         label: 'Sales' },
      { to: '/purchases',      icon: FileSpreadsheet, label: 'Purchases' },
      { to: '/pipeline',       icon: Workflow,        label: 'Pipeline Run' },
      { to: '/exceptions',     icon: AlertTriangle,   label: 'Exceptions' },
    ],
  },
  {
    label: 'Reference',
    items: [
      { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
      { to: '/contacts',  icon: Users,           label: 'Contacts' },
      { to: '/aliases',   icon: BookOpen,        label: 'Vendor Aliases' },
      { to: '/audit',     icon: FileText,        label: 'Audit Trail' },
      { to: '/assistant', icon: Sparkles,        label: 'Assistant' },
    ],
  },
  {
    label: 'Admin',
    items: [
      { to: '/settings', icon: Settings, label: 'Settings' },
    ],
  },
]

// Reveal text/badges only when the rail is EXPANDED — either hovered, or pinned
// open (the aside carries data-pinned="true"). Collapsed: faded out + clipped.
const REVEAL =
  'whitespace-nowrap opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-data-[pinned=true]:opacity-100'

export default function Sidebar() {
  const { user, logout } = useAuth()

  // Pin = lock the rail open (persisted). Unpinned, it auto-collapses to icons
  // and expands on hover.
  const [pinned, setPinned] = useState<boolean>(() => {
    try { return localStorage.getItem('sidebar-pinned') === 'true' } catch { return false }
  })
  const togglePin = () =>
    setPinned((p) => {
      const next = !p
      try { localStorage.setItem('sidebar-pinned', String(next)) } catch { /* ignore */ }
      return next
    })

  // Pending items still to reconcile — shares the ['bank-accounts'] cache with
  // Dashboard, so it's a free read; no backend change.
  const { data: accounts } = useQuery<BankAccount[]>({
    queryKey: ['bank-accounts'],
    queryFn: () => api.get('/bank-accounts/').then((r) => r.data),
  })
  const pendingTotal = (accounts ?? []).reduce((s, a) => s + (a.pending_count || 0), 0)

  return (
    // A real flex item (not an overlay): when it widens, the page content is
    // PUSHED right. Collapsed 64px → expands to 224px on hover, or stays open
    // when pinned. data-pinned drives the expanded reveals + width.
    <aside
      data-pinned={pinned ? 'true' : 'false'}
      className={cn(
        'group relative flex flex-col flex-shrink-0 overflow-hidden shadow-xl',
        'bg-gradient-to-b from-[hsl(84_44%_40%)] via-[hsl(89_46%_32%)] to-[hsl(89_50%_19%)]',
        'transition-[width] duration-200 ease-out',
        pinned ? 'w-56' : 'w-16 hover:w-56',
      )}
    >
      {/* a big faint doodle steeping in the corner, plus a few floating friends */}
      <MatchaMark className="pointer-events-none absolute -bottom-7 left-1/2 -translate-x-1/2 w-44 h-44 text-white/[0.06] animate-sway" />
      <Leaf className="pointer-events-none absolute right-2.5 top-[28%] w-6 h-6 text-white/[0.09] rotate-12 animate-sway" />
      <Sparkle className="pointer-events-none absolute left-2.5 top-[52%] w-5 h-5 text-white/[0.10]" />

      {/* Brand + pin toggle */}
      <div className="relative flex items-center gap-2.5 px-3 py-4 border-b border-white/15">
        <div className="relative w-9 h-9 rounded-2xl bg-white/90 ring-1 ring-black/5 flex items-center justify-center flex-shrink-0 shadow-sm">
          {/* tiny wisp of steam off the cup */}
          <span className="absolute -top-2 left-1/2 -translate-x-1/2 flex gap-[3px] opacity-70">
            {[0, 1, 2].map((i) => (
              <span key={i} className="block w-[2px] h-2 rounded-full bg-white/80 animate-steam" style={{ animationDelay: `${i * 0.5}s` }} />
            ))}
          </span>
          <MatchaCup className="w-7 h-7 group-hover-wiggle" />
        </div>
        <div className={cn('leading-tight min-w-0', REVEAL)}>
          <p className="text-white font-display font-semibold text-base">Matcha</p>
          <p className="text-white/60 text-[10px]">It matches.</p>
        </div>
        <button
          type="button"
          onClick={togglePin}
          title={pinned ? 'Unpin — let the sidebar auto-collapse' : 'Pin the sidebar open'}
          className={cn(
            'ml-auto flex-shrink-0 rounded p-1 text-white/70 hover:text-white hover:bg-white/10 transition-colors',
            REVEAL,
          )}
        >
          {pinned ? <PinOff className="w-3.5 h-3.5" /> : <Pin className="w-3.5 h-3.5" />}
        </button>
      </div>

      {/* Org switcher (collapses to its building icon; full switcher when expanded) */}
      <div className="relative px-3 pt-3 pb-1">
        <OrgSwitcher />
      </div>

      {/* Nav */}
      <nav className="sidebar-scroll relative flex-1 px-2.5 py-2 overflow-y-auto overflow-x-hidden">
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="mb-3">
            <p className={cn('px-3 pt-1 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-white/40', REVEAL)}>
              {group.label}
            </p>
            <div className="space-y-0.5">
              {group.items.map(({ to, icon: Icon, label, badge }) => (
                <NavLink
                  key={to}
                  to={to}
                  title={label}
                  className={({ isActive }) =>
                    cn(
                      'relative flex items-center gap-3 px-3 py-2 rounded-xl text-sm font-medium transition-all duration-150',
                      isActive
                        ? "bg-white/20 text-white shadow-sm before:content-[''] before:absolute before:left-0.5 before:top-1/2 before:-translate-y-1/2 before:h-5 before:w-1 before:rounded-full before:bg-white/90"
                        : 'text-white/65 hover:bg-white/10 hover:text-white hover:translate-x-0.5',
                    )
                  }
                >
                  <span className="relative flex-shrink-0">
                    <Icon className="w-4 h-4" />
                    {/* collapsed-state pending cue: a small dot on the icon */}
                    {badge && pendingTotal > 0 && (
                      <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-amber-400 group-hover:hidden group-data-[pinned=true]:hidden" />
                    )}
                  </span>
                  <span className={cn('flex-1', REVEAL)}>{label}</span>
                  {badge && pendingTotal > 0 && (
                    <span className={cn(
                      'min-w-[1.25rem] text-center rounded-full bg-white/25 text-white text-[10px] font-semibold leading-none px-1.5 py-1',
                      REVEAL,
                    )}>
                      {pendingTotal}
                    </span>
                  )}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      {/* User + logout */}
      <div className="relative px-3 py-3 border-t border-white/10 space-y-2">
        {user && (
          <div className={cn('px-2 py-1 overflow-hidden', REVEAL)}>
            <p className="text-white text-sm font-medium truncate" title={user.name}>
              {user.name || 'User'}
            </p>
            <p className="text-white/55 text-[11px] truncate" title={user.email}>
              {user.email}
            </p>
          </div>
        )}
        <button
          type="button"
          onClick={() => { logout().catch(() => { /* swallow — UI bounces to /login regardless */ }) }}
          title="Logout"
          className={cn(
            'w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium',
            'text-white/75 hover:bg-white/10 hover:text-white transition-colors',
          )}
        >
          <LogOut className="w-4 h-4 flex-shrink-0" />
          <span className={REVEAL}>Logout</span>
        </button>
        <div className={cn('flex items-center justify-center gap-1.5 pt-1', REVEAL)}>
          <MatchaCup className="w-4 h-4" blink={false} />
          <p className="text-white/45 text-[10px]">Matcha · steeped v1</p>
        </div>
      </div>
    </aside>
  )
}
