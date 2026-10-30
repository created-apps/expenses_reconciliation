import { Download } from 'lucide-react'
import { Link, useOutletContext } from 'react-router-dom'
import { toast } from 'sonner'

import { useDownloadExport, useExportSummary } from '@/api/export'
import { Banner } from '@/components/Banner'
import { EmptyState } from '@/components/EmptyState'
import { Button } from '@/components/ui/button'
import { ApiError, errorMessage } from '@/lib/api'
import { formatINR } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { CycleContext } from '@/pages/CycleLayout'

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** "16/10/2026, 09:14" in the viewer's time. */
function formatWhen(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' })
}

/**
 * Export step: what the workbook will hold and whether it adds up to the statement, then the download.
 * Everything shown (counts, totals check, remaining review) comes from the server.
 */
export default function ExportStep() {
  const { cycle } = useOutletContext<CycleContext>()
  const query = useExportSummary(cycle.id)
  const fileName = query.data?.fileName ?? 'CC Expense.xlsx'
  const download = useDownloadExport(cycle.id, fileName)

  if (query.isError) {
    if (query.error instanceof ApiError && query.error.status === 409) {
      return (
        <EmptyState
          title="Nothing to export yet."
          description={`${query.error.message}. The workbook can be downloaded once matching has run.`}
          action={
            <Link to={`/cycles/${cycle.id}/invoices`} className="text-[13px] font-medium text-teal-700 hover:underline">
              Go to Invoices
            </Link>
          }
        />
      )
    }
    return <Banner onRetry={() => void query.refetch()}>{errorMessage(query.error, 'Couldn’t load the export summary.')}</Banner>
  }
  if (query.isPending) {
    return <div className="h-48 max-w-[760px] animate-pulse rounded-md bg-stone-100" aria-busy="true" aria-label="Loading" />
  }

  const s = query.data
  const count = (status: string) => s.statuses.find((x) => x.status === status)?.count ?? 0
  const review = count('Review')
  const missing = count('Missing invoice')
  const other = s.lines - count('Matched') - review - missing

  function downloadExcel() {
    download.mutate(undefined, {
      onSuccess: () => toast(`Downloaded ${fileName}`),
      onError: (error) => toast.error(errorMessage(error, 'Couldn’t build the Excel file. Please try again.')),
    })
  }

  const difference = (value: number | null) =>
    value === null ? (
      <span className="font-semibold text-amber-700">not read</span>
    ) : (
      <span className={cn('font-semibold', value === 0 ? 'text-emerald-700' : 'text-amber-700')}>{formatINR(value)}</span>
    )

  return (
    <div className="max-w-[760px] rounded-md border border-stone-200 bg-white p-5">
      <h2 className="text-[14px] font-semibold">{s.lastExportedAt && !s.editedSinceExport ? 'Exported' : 'Ready to export'}</h2>
      {s.lastExportedAt && (
        <p className="mt-1 text-[12px] text-stone-500">Last exported {formatWhen(s.lastExportedAt)}.</p>
      )}

      <div className="mt-4 grid grid-cols-4 gap-3">
        {(
          [
            ['Matched', count('Matched')],
            ['Review', review],
            ['Missing invoice', missing],
            ['Other', other],
          ] as const
        ).map(([label, value]) => (
          <div key={label}>
            <div className="text-[11px] text-stone-500">{label}</div>
            <div className="mt-1 text-[18px] font-semibold tabular-nums">{value}</div>
          </div>
        ))}
      </div>

      <div className="mt-5 rounded-md bg-stone-50 p-3 text-[12px] tabular-nums text-stone-700">
        <div>
          Debits {formatINR(s.debitsPaise)} · statement{' '}
          {s.printedDebitsPaise === null ? 'not read' : formatINR(s.printedDebitsPaise)} · difference{' '}
          {difference(s.debitsDifferencePaise)}
        </div>
        <div className="mt-1">
          Credits {formatINR(s.creditsPaise)} · statement{' '}
          {s.printedCreditsPaise === null ? 'not read' : formatINR(s.printedCreditsPaise)} · difference{' '}
          {difference(s.creditsDifferencePaise)}
        </div>
      </div>

      {s.editedSinceExport && (
        <Banner tone="warning" className="mt-4">
          Edited since the last export. Download the Excel again to include the changes.
        </Banner>
      )}
      {s.needsReview > 0 && (
        <Banner tone="warning" className="mt-4">
          {plural(s.needsReview, 'line')} still {s.needsReview === 1 ? 'needs' : 'need'} review. You can export anyway.
        </Banner>
      )}
      {!s.totalsOk && (
        <Banner tone="warning" className="mt-4">
          The lines do not add up to the statement’s printed totals. The Summary sheet shows the difference.
        </Banner>
      )}

      <div className="mt-5 border-t border-stone-200 pt-4">
        <h3 className="text-[12px] font-semibold">The workbook includes</h3>
        <ul className="mt-3 flex flex-col gap-2 text-[12px] text-stone-600">
          <li>
            <b>{s.sheets[0]}</b> — counts and amounts per status, and the check against the statement
          </li>
          <li>
            <b>{s.sheetName}</b> — {plural(s.lines, 'statement line')} with matches and notes
          </li>
          <li>
            <b>{s.sheets[2]}</b> — {plural(s.unusedInvoices, 'supplied invoice')} that no line used
          </li>
        </ul>
      </div>

      <div className="mt-5 flex items-center gap-3">
        <Button onClick={downloadExcel} disabled={download.isPending}>
          <Download />
          {download.isPending ? 'Building…' : 'Download Excel'}
        </Button>
        <span className="text-[11px] text-stone-400">{fileName}</span>
      </div>
    </div>
  )
}
