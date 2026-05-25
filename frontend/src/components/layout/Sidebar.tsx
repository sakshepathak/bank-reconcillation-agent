import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, RefreshCw, CheckSquare,
  Users, FileText, BookOpen, Settings, Building2,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/dashboard',       icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/reconciliation',  icon: RefreshCw,        label: 'Reconciliation' },
  { to: '/review',          icon: CheckSquare,      label: 'Review Queue' },
  { to: '/contacts',        icon: Users,            label: 'Contacts' },
  { to: '/audit',           icon: FileText,         label: 'Audit Trail' },
  { to: '/aliases',         icon: BookOpen,         label: 'Vendor Aliases' },
  { to: '/settings',        icon: Settings,         label: 'Settings' },
]

export default function Sidebar() {
  return (
    <aside className="w-56 h-full flex-shrink-0 flex flex-col bg-gradient-to-b from-indigo-700 to-indigo-500 shadow-xl">
      {/* Brand */}
      <div className="px-5 py-4 border-b border-white/15">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-white/20 flex items-center justify-center">
            <Building2 className="w-4 h-4 text-white" />
          </div>
          <span className="text-white font-semibold text-sm tracking-tight">Reconcile</span>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-2.5 space-y-0.5 overflow-y-auto">
        {NAV.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-150',
                isActive
                  ? 'bg-white/20 text-white shadow-sm'
                  : 'text-white/65 hover:bg-white/10 hover:text-white',
              )
            }
          >
            <Icon className="w-4 h-4 flex-shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-white/10">
        <p className="text-white/40 text-xs text-center">Reconciliation Engine v1</p>
      </div>
    </aside>
  )
}
