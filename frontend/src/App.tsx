import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Toaster } from 'sonner'

import { AuthProvider } from '@/auth/AuthProvider'
import ProtectedRoute from '@/auth/ProtectedRoute'
import AppShell from '@/components/AppShell'
import CycleLayout, { CycleIndexRedirect } from '@/pages/CycleLayout'
import Cycles from '@/pages/Cycles'
import ExportStep from '@/pages/ExportStep'
import InvoicesStep from '@/pages/InvoicesStep'
import Login from '@/pages/Login'
import NewCycle from '@/pages/NewCycle'
import NotFound from '@/pages/NotFound'
import ResultsStep from '@/pages/ResultsStep'
import StatementStep from '@/pages/StatementStep'

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: 1, staleTime: 5_000, refetchOnWindowFocus: false } },
  })
}

// Routes from design.md section 3. Every screen is real: cycles, uploads, the statement, invoices,
// matching, results and review, and the Excel export. No mock-data screen is left.
export function AppRoutes() {
  return (
    <>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<AppShell />}>
            <Route path="/" element={<Cycles />} />
            <Route path="/cycles/new" element={<NewCycle />} />
            <Route path="/cycles/:id" element={<CycleLayout />}>
              <Route index element={<CycleIndexRedirect />} />
              <Route path="statement" element={<StatementStep />} />
              <Route path="invoices" element={<InvoicesStep />} />
              <Route path="results" element={<ResultsStep />} />
              <Route path="export" element={<ExportStep />} />
            </Route>
            <Route path="*" element={<NotFound />} />
          </Route>
        </Route>
      </Routes>
      <Toaster position="bottom-right" theme="light" toastOptions={{ classNames: { toast: 'text-[13px]' } }} />
    </>
  )
}

const queryClient = createQueryClient()

export default function App() {
  return (
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </QueryClientProvider>
    </BrowserRouter>
  )
}
