import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import AppShell from '@/components/layout/AppShell'
import Dashboard from '@/pages/Dashboard'
import Reconciliation from '@/pages/Reconciliation'
import ReviewQueue from '@/pages/ReviewQueue'
import Contacts from '@/pages/Contacts'
import AuditTrail from '@/pages/AuditTrail'
import Aliases from '@/pages/Aliases'
import Settings from '@/pages/Settings'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard"      element={<Dashboard />} />
          <Route path="reconciliation" element={<Reconciliation />} />
          <Route path="review"         element={<ReviewQueue />} />
          <Route path="contacts"       element={<Contacts />} />
          <Route path="audit"          element={<AuditTrail />} />
          <Route path="aliases"        element={<Aliases />} />
          <Route path="settings"       element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
