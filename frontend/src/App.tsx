import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import AppShell from '@/components/layout/AppShell'
import RequireAuth from '@/components/RequireAuth'
import RequireOrg from '@/components/RequireOrg'
import { AuthProvider } from '@/lib/auth-context'

import Dashboard from '@/pages/Dashboard'
import Sales from '@/pages/Sales'
import Purchases from '@/pages/Purchases'
import BankAccounts from '@/pages/BankAccounts'
import Reconciliation from '@/pages/Reconciliation'
import Assistant from '@/pages/Assistant'
import Exceptions from '@/pages/ReviewQueue'   // folder kept; exported component is Exceptions
import Contacts from '@/pages/Contacts'
import ContactDetailPage from '@/pages/Contacts/detail'
import AuditTrail from '@/pages/AuditTrail'
import Aliases from '@/pages/Aliases'
import Settings from '@/pages/Settings'

import Login from '@/pages/Login'
import Register from '@/pages/Register'
import Onboarding from '@/pages/Onboarding'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          {/* Public routes — no shell, no auth required */}
          <Route path="/login"    element={<Login />} />
          <Route path="/register" element={<Register />} />

          {/* Logged-in but no-org-yet route — gated by auth, NOT by org.
              This is what RequireOrg redirects TO, so it must not also be
              wrapped in RequireOrg or we'd loop. */}
          <Route
            path="/onboarding"
            element={
              <RequireAuth>
                <Onboarding />
              </RequireAuth>
            }
          />

          {/* App pages — require BOTH a logged-in session AND a current org. */}
          <Route
            path="/"
            element={
              <RequireAuth>
                <RequireOrg>
                  <AppShell />
                </RequireOrg>
              </RequireAuth>
            }
          >
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard"      element={<Dashboard />} />
            <Route path="sales"          element={<Sales />} />
            <Route path="purchases"      element={<Purchases />} />
            <Route path="bank-accounts"  element={<BankAccounts />} />
            <Route path="reconciliation" element={<Reconciliation />} />
            <Route path="assistant"      element={<Assistant />} />
            <Route path="exceptions"     element={<Exceptions />} />
            <Route path="contacts"       element={<Contacts />} />
            <Route path="contacts/:id"   element={<ContactDetailPage />} />
            <Route path="audit"          element={<AuditTrail />} />
            <Route path="aliases"        element={<Aliases />} />
            <Route path="settings"       element={<Settings />} />
          </Route>

          {/* Fallback for unknown paths */}
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
