import { useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Navigate, useNavigate, useOutletContext } from 'react-router-dom'
import { toast } from 'sonner'

import { useAmazonReport } from '@/api/amazon'
import { cycleKeys } from '@/api/cycles'
import { useInvoices, useReadInvoices, type InvoiceEntry } from '@/api/invoices'
import { useRunMatching } from '@/api/matching'
import { AddFilesSheet } from '@/components/AddFilesSheet'
import { AmazonReportPanel, NoAmazonReport } from '@/components/AmazonReportPanel'
import { Banner } from '@/components/Banner'
import { EmptyState } from '@/components/EmptyState'
import { FilterChips, type ChipOption } from '@/components/FilterChips'
import { InvoiceSheet } from '@/components/InvoiceSheet'
import { JobProgress } from '@/components/JobProgress'
import { ExtractionBadge } from '@/components/StatusBadge'
import { TableSkeleton } from '@/components/TableSkeleton'
import { Button } from '@/components/ui/button'
import { errorMessage } from '@/lib/api'
import { reachedIndex } from '@/lib/cycleSteps'
import { formatDate } from '@/lib/format'
import { SOURCE_LABEL } from '@/lib/invoiceLabels'
import { formatInvoiceTotal } from '@/lib/money'
import { cn } from '@/lib/utils'
import type { CycleContext } from '@/pages/CycleLayout'

type Filter = 'all' | 'needs_check' | 'pending' | 'duplicate' | 'ignored' | 'failed'

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/**
 * Invoices step. Needs a confirmed statement: without one it sends you back to the Statement step
 * (the server refuses the read as well). Reading the images comes in Slice 7, matching in Slice 9.
 */
export default function InvoicesStep() {
  const { cycle } = useOutletContext<CycleContext>()
  if (reachedIndex(cycle.status) < 1) return <Navigate replace to={`/cycles/${cycle.id}/statement`} />
  return <InvoicesView cycleId={cycle.id} cycleStatus={cycle.status} />
}

function InvoicesView({ cycleId, cycleStatus }: { cycleId: string; cycleStatus: string }) {
  const queryClient = useQueryClient()
  const amazon = useAmazonReport(cycleId)
  const query = useInvoices(cycleId)
  const read = useReadInvoices(cycleId)
  const matching = useRunMatching(cycleId)
  const navigate = useNavigate()
  const [filter, setFilter] = useState<Filter>('all')
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [addOpen, setAddOpen] = useState(false)
  const [newFiles, setNewFiles] = useState(0)
  const view = query.data

  // The cycle's status moves when a read finishes; keep the stepper and the home list in step.
  useEffect(() => {
    if (view && view.status !== cycleStatus) {
      void queryClient.invalidateQueries({ queryKey: cycleKeys.one(cycleId) })
      void queryClient.invalidateQueries({ queryKey: cycleKeys.all })
    }
  }, [view, cycleStatus, cycleId, queryClient])

  const entries = useMemo(() => view?.entries ?? [], [view])
  const selected = entries.find((e) => e.key === selectedKey) ?? null

  const chips: ChipOption<Filter>[] = useMemo(() => {
    const c = view?.counts
    const chip = (value: Filter, label: string, n: number | null): ChipOption<Filter> => ({
      value,
      label: n === null ? label : `${label} (${n})`,
    })
    return [
      chip('all', 'All', null),
      chip('needs_check', 'Needs check', c?.needsCheck ?? 0),
      chip('pending', 'Waiting for AI', c?.pending ?? 0),
      chip('duplicate', 'Duplicates', (c?.duplicateFiles ?? 0) + (c?.duplicateInvoices ?? 0)),
      chip('ignored', 'Ignored', c?.ignored ?? 0),
      ...(c && c.failed > 0 ? [chip('failed', 'Failed', c.failed)] : []),
    ]
  }, [view])

  const shown = entries.filter((e) => filter === 'all' || e.state === (filter === 'needs_check' ? 'needs_check' : filter))

  if (query.isError) {
    return <Banner onRetry={() => void query.refetch()}>{errorMessage(query.error, 'Couldn’t load the invoices.')}</Banner>
  }

  const job = view?.job
  const running = job?.status === 'running' || read.isPending
  const counts = view?.counts
  const hasRead = counts ? counts.invoices + counts.pending + counts.failed > 0 : false

  function runMatching() {
    // The run works in the background; the Results step shows its progress and says when it has finished.
    matching.mutate(undefined, {
      onSuccess: () => navigate(`/cycles/${cycleId}/results`),
      onError: (error) => toast.error(errorMessage(error, 'Couldn’t start the matching. Please try again.')),
    })
  }

  function readInvoices() {
    read.mutate(undefined, {
      onError: (error) => toast.error(errorMessage(error, 'Couldn’t start reading the invoices.')),
    })
  }

  return (
    <>
      {running && <JobProgress message={job?.message || 'Reading invoices…'} progress={job?.progress ?? 0} />}

      <div className={cn(running && 'pointer-events-none opacity-50')} aria-busy={running}>
        {job?.status === 'failed' && (
          <Banner onRetry={readInvoices} className="mb-4">
            {job.message}
          </Banner>
        )}

        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-[13px] text-stone-600">
            {!counts ? (
              <span className="inline-block h-4 w-64 animate-pulse rounded bg-stone-100 align-middle" />
            ) : !hasRead ? (
              <>
                <b>{plural(counts.files, 'file')}</b> uploaded · not read yet
                {counts.duplicateFiles > 0 && <> · {plural(counts.duplicateFiles, 'duplicate')}</>}
                {counts.ignored > 0 && <> · {counts.ignored} ignored</>}
              </>
            ) : (
              <>
                <b>{plural(counts.files, 'file')}</b> · {plural(counts.invoices, 'invoice')}
                {counts.pending > 0 && <> · {plural(counts.pending, 'image')} waiting for AI</>}
                {counts.needsCheck > 0 && <span className="text-amber-700"> · {counts.needsCheck} need a check</span>}
                {counts.duplicateFiles + counts.duplicateInvoices > 0 && (
                  <> · {plural(counts.duplicateFiles + counts.duplicateInvoices, 'duplicate')}</>
                )}
                {counts.ignored > 0 && <> · {counts.ignored} ignored</>}
                {counts.failed > 0 && <span className="text-red-700"> · {counts.failed} failed</span>}
              </>
            )}
          </p>
          <div className="flex items-center gap-2">
            <Button variant="secondary" onClick={() => setAddOpen(true)}>
              <Plus />
              Add files
            </Button>
            <Button onClick={readInvoices} disabled={running || !counts}>
              Read invoices
            </Button>
            <Button onClick={runMatching} disabled={running || matching.isPending || !counts}>
              {matching.isPending ? 'Matching…' : 'Run matching'}
            </Button>
          </div>
        </div>

        {newFiles > 0 && (
          <Banner tone="warning" className="mt-3">
            {plural(newFiles, 'new file')}. Read invoices again to include them.
          </Banner>
        )}

        {amazon.isSuccess &&
          (amazon.data.file ? <AmazonReportPanel report={amazon.data} /> : <NoAmazonReport />)}
        {amazon.isError && (
          <p className="mt-3 text-[12px] text-red-700">Couldn’t load the Amazon report. Reload the page to try again.</p>
        )}

        {entries.length > 0 && (
          <div className="mt-4">
            <FilterChips options={chips} value={filter} onChange={setFilter} />
          </div>
        )}

        <div className="mt-4 overflow-x-auto rounded-md border border-stone-200 bg-white">
          {query.isPending ? (
            <TableSkeleton />
          ) : entries.length === 0 ? (
            <div className="p-4">
              <EmptyState
                title="No invoices uploaded yet."
                description="Add the invoices for this statement period."
                action={<Button onClick={() => setAddOpen(true)}>Add files</Button>}
              />
            </div>
          ) : shown.length === 0 ? (
            <div className="p-4">
              <EmptyState title="No invoices in this filter." />
            </div>
          ) : (
            <table className="w-full min-w-[760px] text-left text-[12px]">
              <thead className="bg-stone-50 text-[11px] font-medium uppercase tracking-wide text-stone-500">
                <tr>
                  <th className="px-4 py-3">File name</th>
                  <th className="py-3">Vendor</th>
                  <th className="py-3">Invoice no.</th>
                  <th className="py-3">Date</th>
                  <th className="py-3 text-right">Amount</th>
                  <th className="py-3 pl-4">Source</th>
                  <th className="py-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((e) => (
                  <Row key={e.key} entry={e} siblings={entries} onOpen={() => setSelectedKey(e.key)} />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <InvoiceSheet
        entry={selected}
        vendors={view?.vendors ?? []}
        cycleId={cycleId}
        onClose={() => setSelectedKey(null)}
      />
      <AddFilesSheet
        cycleId={cycleId}
        open={addOpen}
        onOpenChange={setAddOpen}
        onDone={(count) => {
          setNewFiles((n) => n + count)
          setAddOpen(false)
        }}
      />
    </>
  )
}

function Row({ entry: e, siblings, onOpen }: { entry: InvoiceEntry; siblings: InvoiceEntry[]; onOpen: () => void }) {
  const several = e.invoiceId !== null && siblings.filter((s) => s.fileId === e.fileId).length > 1
  const hasInvoice = e.invoiceId !== null && e.totalMinor !== null && e.currency !== null
  return (
    <tr
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === 'Enter') onOpen()
      }}
      tabIndex={0}
      className="cursor-pointer border-t border-stone-100 outline-none hover:bg-stone-50 focus-visible:bg-stone-50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-teal-600/40"
    >
      <td className="px-4 py-3 font-medium text-stone-800">
        {e.fileName}
        {several && <span className="ml-1 font-normal text-stone-400">· invoice {(e.blockIndex ?? 0) + 1}</span>}
      </td>
      <td>{e.vendorName ?? '—'}</td>
      <td className="text-stone-500">{e.invoiceNo ?? '—'}</td>
      <td className="tabular-nums">{formatDate(e.invoiceDate ?? e.orderDate)}</td>
      <td className="text-right tabular-nums">
        {hasInvoice ? formatInvoiceTotal({ currency: e.currency!, totalMinor: e.totalMinor! }) : '—'}
        {e.isCreditNote && <span className="ml-1 text-[11px] text-stone-400">credit</span>}
      </td>
      <td className="pl-4 text-stone-500">{e.source ? SOURCE_LABEL[e.source] : '—'}</td>
      <td>
        <ExtractionBadge state={e.state} />
      </td>
    </tr>
  )
}
