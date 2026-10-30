import { ChevronRight, MoreHorizontal, Plus } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { useCycles, useDeleteCycle } from '@/api/cycles'
import { Banner } from '@/components/Banner'
import { CycleStatusBadge } from '@/components/CycleStatusBadge'
import { EmptyState } from '@/components/EmptyState'
import { PageHeader } from '@/components/PageHeader'
import { TableSkeleton } from '@/components/TableSkeleton'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { errorMessage } from '@/lib/api'
import { stepForStatus } from '@/lib/cycleSteps'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { Cycle } from '@/types'

const UNTITLED = 'Untitled reconciliation'

export default function Cycles() {
  const navigate = useNavigate()
  const cycles = useCycles()
  const deleteCycle = useDeleteCycle()
  const [toDelete, setToDelete] = useState<Cycle | null>(null)

  const rows = cycles.data ?? []

  return (
    <>
      <PageHeader
        title="Reconciliations"
        description="Review card statements and invoices each month."
        action={
          <Button onClick={() => navigate('/cycles/new')}>
            <Plus />
            New reconciliation
          </Button>
        }
      />

      <div className="mt-6">
        {cycles.isPending ? (
          <div className="overflow-hidden rounded-md border border-stone-200 bg-white">
            <TableSkeleton />
          </div>
        ) : cycles.isError ? (
          <Banner onRetry={() => void cycles.refetch()}>{errorMessage(cycles.error, 'Couldn’t load the reconciliations.')}</Banner>
        ) : rows.length === 0 ? (
          <EmptyState
            title="No reconciliations yet."
            description="Add a card statement and its invoices to start."
            action={<Button onClick={() => navigate('/cycles/new')}>New reconciliation</Button>}
          />
        ) : (
          <div className="overflow-x-auto rounded-md border border-stone-200 bg-white">
            <table className="w-full min-w-[760px] text-left text-[13px]">
              <thead className="border-b border-stone-200 bg-stone-50/70 text-[11px] font-medium uppercase tracking-wide text-stone-500">
                <tr>
                  <th className="px-4 py-3">Month</th>
                  <th className="px-2 py-3">Statement period</th>
                  <th className="px-2 py-3">Status</th>
                  <th className="px-2 py-3">Progress</th>
                  <th className="px-2 py-3">Open items</th>
                  <th className="px-2 py-3">Last updated</th>
                  <th className="px-2 py-3">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => {
                  const total = c.totalLines ?? 0
                  const pct = total > 0 && c.matchedLines !== null ? (c.matchedLines / total) * 100 : 0
                  const target = `/cycles/${c.id}/${stepForStatus(c.status)}`
                  const name = c.label ?? UNTITLED
                  return (
                    <tr
                      key={c.id}
                      onClick={() => navigate(target)}
                      className="cursor-pointer border-b border-stone-100 last:border-0 hover:bg-stone-50"
                    >
                      <td className="px-4 py-4 font-medium text-stone-900">
                        <Link
                          to={target}
                          onClick={(e) => e.stopPropagation()}
                          className={cn('rounded outline-none focus-visible:ring-2 focus-visible:ring-teal-600/40', !c.label && 'text-stone-600')}
                        >
                          {name}
                        </Link>
                        {!c.label && (
                          <span className="ml-2 text-[11px] font-normal text-stone-400">created {formatDate(c.createdAt)}</span>
                        )}
                      </td>
                      <td className="px-2 tabular-nums text-stone-600">
                        {c.periodStart && c.periodEnd ? `${formatDate(c.periodStart)} – ${formatDate(c.periodEnd)}` : '—'}
                      </td>
                      <td className="px-2">
                        <CycleStatusBadge status={c.status} />
                      </td>
                      <td className="min-w-[180px] px-2">
                        {c.matchedLines === null ? (
                          <span className="text-stone-400">—</span>
                        ) : (
                          <div className="flex items-center gap-2">
                            <span className="tabular-nums text-stone-600">
                              {c.matchedLines} of {c.totalLines} matched
                            </span>
                            <div className="h-1.5 w-16 rounded-full bg-stone-100">
                              <div className="h-1.5 rounded-full bg-teal-700" style={{ width: `${pct}%` }} />
                            </div>
                          </div>
                        )}
                      </td>
                      <td className={cn('px-2 tabular-nums', c.openItems ? 'font-medium text-amber-700' : 'text-stone-600')}>
                        {c.openItems === null ? '—' : c.openItems}
                      </td>
                      <td className="px-2 tabular-nums text-stone-500">{formatDate(c.updatedAt)}</td>
                      <td className="pr-4 text-right text-stone-400" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-end gap-1">
                          {c.status !== 'exported' && (
                            <DropdownMenu>
                              <DropdownMenuTrigger
                                aria-label={`Actions for ${name}`}
                                className="rounded p-1 text-stone-400 outline-none hover:bg-stone-100 hover:text-stone-700 focus-visible:ring-2 focus-visible:ring-teal-600/40"
                              >
                                <MoreHorizontal className="size-4" />
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end" className="w-36">
                                <DropdownMenuItem variant="destructive" onClick={() => setToDelete(c)}>
                                  Delete
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          )}
                          <ChevronRight className="size-4" />
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <Dialog open={toDelete !== null} onOpenChange={(open) => !open && !deleteCycle.isPending && setToDelete(null)}>
        <DialogContent showCloseButton={false} className="rounded-md bg-white sm:max-w-md">
          <DialogTitle className="text-[16px] font-semibold text-stone-900">Delete reconciliation</DialogTitle>
          <DialogDescription className="text-[13px] text-stone-600">
            Delete {toDelete?.label ?? UNTITLED} and its uploaded files? This can’t be undone.
          </DialogDescription>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" disabled={deleteCycle.isPending} onClick={() => setToDelete(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={deleteCycle.isPending}
              onClick={() => {
                if (!toDelete) return
                deleteCycle.mutate(toDelete.id, {
                  onSuccess: () => toast(`${toDelete.label ?? UNTITLED} deleted`),
                  onError: (error) => toast.error(errorMessage(error, 'Could not delete the reconciliation.')),
                  onSettled: () => setToDelete(null),
                })
              }}
            >
              {deleteCycle.isPending ? 'Deleting…' : 'Delete'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
