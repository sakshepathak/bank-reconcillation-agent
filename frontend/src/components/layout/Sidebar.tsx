import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, RefreshCw, AlertTriangle, Receipt, FileSpreadsheet,
  Landmark, Users, FileText, BookOpen, Settings, LogOut,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import OrgSwitcher from '@/components/OrgSwitcher'

const NAV = [
  { to: '/dashboard',       icon: LayoutDashboard,  label: 'Dashboard' },
  { to: '/sales',           icon: Receipt,          label: 'Sales' },
  { to: '/purchases',       icon: FileSpreadsheet,  label: 'Purchases' },
  { to: '/bank-accounts',   icon: Landmark,         label: 'Bank Accounts' },
  { to: '/reconciliation',  icon: RefreshCw,        label: 'Reconcile' },
  { to: '/exceptions',      icon: AlertTriangle,    label: 'Exceptions' },
  { to: '/contacts',        icon: Users,            label: 'Contacts' },
  { to: '/audit',           icon: FileText,         label: 'Audit Trail' },
  { to: '/aliases',         icon: BookOpen,         label: 'Vendor Aliases' },
  { to: '/settings',        icon: Settings,         label: 'Settings' },
]

export default function Sidebar() {
  const { user, logout } = useAuth()

  return (
    <aside className="w-56 h-full flex-shrink-0 flex flex-col bg-gradient-to-b from-indigo-700 to-indigo-500 shadow-xl">
      {/* Brand */}
      <div className="px-5 py-4 border-b border-white/15">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-lg bg-white/15 flex items-center justify-center">
            <span className="text-white font-black text-base tracking-tight">OOO</span>
          </div>
          <div className="leading-tight">
            <p className="text-white font-semibold text-sm">OOO</p>
            <p className="text-white/60 text-[10px]">Bank Reconciliation</p>
          </div>
        </div>
      </div>

      {/* Org switcher */}
      <div className="px-3 pt-3 pb-1">
        <OrgSwitcher />
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

      {/* User + logout */}
      <div className="px-3 py-3 border-t border-white/10 space-y-2">
        {user && (
          <div className="px-2 py-1">
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
          className={cn(
            'w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium',
            'text-white/75 hover:bg-white/10 hover:text-white transition-colors',
          )}
        >
          <LogOut className="w-4 h-4" />
          Logout
        </button>
        <p className="text-white/40 text-[10px] text-center pt-1">OOO · v1</p>
      </div>
    </aside>
  )
}
