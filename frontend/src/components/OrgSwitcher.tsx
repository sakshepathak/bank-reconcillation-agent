/**
 * Organization switcher — Radix dropdown anchored in the sidebar.
 *
 * Shows the current org's name; clicking opens a list of every org the
 * user belongs to, plus a "+ Add new organisation" entry that navigates to
 * /onboarding. With only one org (the common v1 case) the dropdown still
 * works and the add-new entry is what makes multi-org possible.
 */
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { Building2, Check, ChevronsUpDown, Plus } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/lib/auth-context'
import { cn } from '@/lib/utils'

export default function OrgSwitcher() {
  const { user, switchOrg } = useAuth()
  const [busyId, setBusyId] = useState<number | null>(null)
  const navigate = useNavigate()

  if (!user) return null

  const current = user.orgs.find((o) => o.id === user.current_org_id) ?? user.orgs[0]

  async function handleSwitch(orgId: number) {
    if (orgId === user!.current_org_id) return
    setBusyId(orgId)
    try {
      await switchOrg(orgId)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className={cn(
            // Solid surface — the previous bg-white/10 was near-invisible on the
            // indigo sidebar and below the dropdown when expanded.
            'w-full flex items-center justify-between gap-2 px-3 py-2 rounded-lg',
            'bg-white text-indigo-900 text-sm font-semibold shadow-sm',
            'hover:bg-white/95 transition-colors',
            'data-[state=open]:ring-2 data-[state=open]:ring-white/60',
          )}
        >
          <span className="flex items-center gap-2 min-w-0">
            <Building2 className="w-4 h-4 flex-shrink-0 text-indigo-600" />
            <span className="truncate">{current?.name ?? 'No organization'}</span>
          </span>
          <ChevronsUpDown className="w-3.5 h-3.5 flex-shrink-0 text-indigo-500" />
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="start"
          sideOffset={6}
          className={cn(
            // Force solid white background + clear border + meaningful shadow.
            // bg-popover was rendering near-transparent on this theme — the user
            // could barely read the menu against the page behind it.
            'z-50 min-w-[220px] rounded-lg border border-slate-200 bg-white p-1.5 shadow-xl',
            'data-[state=open]:animate-in data-[state=closed]:animate-out',
            'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
          )}
        >
          <DropdownMenu.Label className="px-2 py-1.5 text-[11px] font-semibold text-slate-500 uppercase tracking-wide">
            Your organisations
          </DropdownMenu.Label>
          {user.orgs.map((o) => {
            const active = o.id === user.current_org_id
            return (
              <DropdownMenu.Item
                key={o.id}
                onSelect={(e) => {
                  e.preventDefault()
                  handleSwitch(o.id)
                }}
                className={cn(
                  'flex items-center gap-2 px-2 py-2 rounded-md text-sm cursor-pointer',
                  'outline-none text-slate-700',
                  'focus:bg-indigo-50 focus:text-indigo-900',
                  active && 'font-semibold text-indigo-900 bg-indigo-50/60',
                )}
              >
                <Building2 className="w-3.5 h-3.5 flex-shrink-0 text-slate-400" />
                <span className="flex-1 truncate">{o.name}</span>
                {active && <Check className="w-4 h-4 text-indigo-600 flex-shrink-0" />}
                {busyId === o.id && (
                  <span className="text-xs text-slate-500">switching…</span>
                )}
              </DropdownMenu.Item>
            )
          })}

          <DropdownMenu.Separator className="my-1 h-px bg-slate-100" />

          <DropdownMenu.Item
            onSelect={(e) => {
              e.preventDefault()
              navigate('/onboarding')
            }}
            className={cn(
              'flex items-center gap-2 px-2 py-2 rounded-md text-sm cursor-pointer',
              'outline-none text-indigo-700 font-medium',
              'focus:bg-indigo-50',
            )}
          >
            <Plus className="w-4 h-4 flex-shrink-0" />
            <span>Add new organisation</span>
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
