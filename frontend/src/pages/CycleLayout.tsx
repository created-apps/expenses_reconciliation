import { ArrowLeft } from 'lucide-react'
import { Link, Navigate, Outlet, useLocation, useNavigate, useOutletContext, useParams } from 'react-router-dom'

import { useCycle, type CycleDetail } from '@/api/cycles'
import { Banner } from '@/components/Banner'
import { EmptyState } from '@/components/EmptyState'
import { PageHeader } from '@/components/PageHeader'
import { STEPS, Stepper, type StepKey } from '@/components/Stepper'
import { ApiError, errorMessage } from '@/lib/api'
import { reachedIndex, stepForStatus } from '@/lib/cycleSteps'
import { formatDate } from '@/lib/format'

export type CycleContext = { cycle: CycleDetail }

export default function CycleLayout() {
  const { id } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const query = useCycle(id)

  if (query.isPending) {
    return (
      <div aria-busy="true" aria-label="Loading">
        <div className="mb-3 h-3 w-32 animate-pulse rounded bg-stone-100" />
        <div className="h-7 w-48 animate-pulse rounded bg-stone-100" />
        <div className="mt-3 h-3 w-72 animate-pulse rounded bg-stone-100" />
      </div>
    )
  }

  if (query.isError) {
    const missing = query.error instanceof ApiError && (query.error.status === 404 || query.error.status === 422)
    return missing ? (
      <EmptyState
        title="Reconciliation not found."
        action={
          <Link to="/" className="text-[13px] font-medium text-teal-700">
            All reconciliations
          </Link>
        }
      />
    ) : (
      <Banner onRetry={() => void query.refetch()}>{errorMessage(query.error, 'Couldn’t load this reconciliation.')}</Banner>
    )
  }

  const cycle = query.data
  const last = location.pathname.split('/').filter(Boolean).pop()
  const active: StepKey = STEPS.some((s) => s.key === last) ? (last as StepKey) : 'statement'
  const period =
    cycle.periodStart && cycle.periodEnd
      ? `Statement ${formatDate(cycle.periodStart)} – ${formatDate(cycle.periodEnd)} · ICICI`
      : 'The statement period is read from the statement PDF'

  return (
    <>
      <Link to="/" className="mb-3 inline-flex items-center gap-1 text-[12px] text-stone-500 hover:text-stone-900">
        <ArrowLeft className="size-3.5" />
        All reconciliations
      </Link>
      <PageHeader title={cycle.label ?? 'New reconciliation'} description={period} />
      <Stepper
        active={active}
        reachedIndex={reachedIndex(cycle.status)}
        onSelect={(step) => navigate(`/cycles/${cycle.id}/${step}`)}
      />
      {cycle.editedSinceExport && (
        <Banner tone="warning" className="mb-4">
          Edited since the last export
          {cycle.lastExportedAt ? ` (${new Date(cycle.lastExportedAt).toLocaleDateString('en-GB')})` : ''}. The Excel you
          downloaded no longer matches what is shown here. Download it again on the Export step.
        </Banner>
      )}
      <Outlet context={{ cycle } satisfies CycleContext} />
    </>
  )
}

/** `/cycles/:id` opens the step the cycle has reached. */
export function CycleIndexRedirect() {
  const { cycle } = useOutletContext<CycleContext>()
  return <Navigate replace to={`/cycles/${cycle.id}/${stepForStatus(cycle.status)}`} />
}
