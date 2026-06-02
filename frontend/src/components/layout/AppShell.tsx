import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import { useAuth } from '@/lib/auth-context'

export default function AppShell() {
  const { user } = useAuth()

  return (
    <div className="flex h-screen bg-background overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <main className="flex-1 overflow-y-auto">
          <div className="max-w-[1280px] mx-auto px-6 py-6">
            {/* key forces a full remount of every page component when the org
                changes — all useQuery hooks re-initialize, caches start empty,
                and the correct org's data loads immediately with no stale bleed. */}
            <Outlet key={user?.current_org_id ?? 'no-org'} />
          </div>
        </main>
      </div>
    </div>
  )
}
