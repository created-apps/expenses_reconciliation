import { useQueryClient } from '@tanstack/react-query'
import { ChevronRight, Download } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useOutletContext } from 'react-router-dom'
import { toast } from 'sonner'

import { cycleKeys, openStoredFile, useCycleFiles } from '@/api/cycles'
import { useConfirmStatement, useReadStatement, useStatement } from '@/api/statement'
import { storedFileRow, useUploader } from '@/api/useUploader'
import { Banner } from '@/components/Banner'
import { FileRow } from '@/components/FileRow'
import { JobProgress } from '@/components/JobProgress'
import { StatTile } from '@/components/StatTile'
import { TableSkeleton } from '@/components/TableSkeleton'
import { UploadCard } from '@/components/UploadCard'
import { Button } from '@/components/ui/button'
import { errorMessage } from '@/lib/api'
import { formatDate, formatForeign, formatINR } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { CycleContext } from '@/pages/CycleLayout'

const dateTime = new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short' })

/**
 * Statement step: read the uploaded PDF into lines, show them against the totals the statement prints,
 * and confirm. Every figure and every pass/fail comes from the API.
 */
export default function StatementStep() {
  const { cycle } = useOutletContext<CycleContext>()
  const files = useCycleFiles(cycle.id)
  const [replacing, setReplacing] = useState(false)
  const uploader = useUploader({ slot: 'statement', getCycleId: () => Promise.resolve(cycle.id) })

  const statement = files.data?.find((f) => f.kind === 'statement' && f.status !== 'duplicate')
  // A statement can be replaced until it is confirmed.
  const canReplace = cycle.status === 'draft' || cycle.status === 'statement_parsed'

  if (files.isError) {
    return <Banner onRetry={() => void files.refetch()}>{errorMessage(files.error, 'Couldn’t load the files.')}</Banner>
  }

  if (files.isPending) {
    return (
      <div className="overflow-hidden rounded-md border border-stone-200 bg-white">
        <TableSkeleton rows={3} />
      </div>
    )
  }

  if (!statement || replacing) {
    return (
      <div className="max-w-[760px] space-y-3">
        <UploadCard
          title="Card statement"
          hint="Required · one PDF"
          helper={
            statement
              ? 'A new statement replaces the current one and its lines.'
              : 'Download the PDF from ICICI net banking. Photos aren’t supported.'
          }
          accept=".pdf,application/pdf"
          rows={uploader.rows}
          onAdd={(picked) => {
            void uploader.addFiles(picked).then(() => setReplacing(false))
          }}
          onDismiss={uploader.dismiss}
        />
        {statement && (
          <Button variant="secondary" onClick={() => setReplacing(false)}>
            Cancel
          </Button>
        )}
      </div>
    )
  }

  return (
    <ReadStatement
      cycleId={cycle.id}
      cycleStatus={cycle.status}
      statementFileId={statement.id}
      fileRow={<FileRow row={storedFileRow(statement)} />}
      onReplace={canReplace ? () => setReplacing(true) : undefined}
    />
  )
}

function ReadStatement({
  cycleId,
  cycleStatus,
  statementFileId,
  fileRow,
  onReplace,
}: {
  cycleId: string
  cycleStatus: string
  statementFileId: string
  fileRow: React.ReactNode
  onReplace?: () => void
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const query = useStatement(cycleId)
  const read = useReadStatement(cycleId)
  const confirm = useConfirmStatement(cycleId)
  const [search, setSearch] = useState('')
  const loaded = query.data

  // The cycle's status moves when a read finishes; keep the stepper and the home list in step.
  useEffect(() => {
    if (loaded && loaded.status !== cycleStatus) {
      void queryClient.invalidateQueries({ queryKey: cycleKeys.one(cycleId) })
      void queryClient.invalidateQueries({ queryKey: cycleKeys.all })
    }
  }, [loaded, cycleStatus, cycleId, queryClient])

  const lines = useMemo(() => {
    const all = loaded?.lines ?? []
    const q = search.trim().toLowerCase()
    return q ? all.filter((l) => l.serNo.includes(q) || l.description.toLowerCase().includes(q)) : all
  }, [loaded, search])

  if (query.isError) {
    return <Banner onRetry={() => void query.refetch()}>{errorMessage(query.error, 'Couldn’t load the statement.')}</Banner>
  }
  if (query.isPending) {
    return (
      <div className="overflow-hidden rounded-md border border-stone-200 bg-white">
        <TableSkeleton rows={4} />
      </div>
    )
  }

  const view = query.data
  const job = view.job
  const running = job?.status === 'running' || read.isPending
  const confirmed = view.status === 'statement_confirmed'
  const hasLines = view.lines.length > 0
  const check = view.check

  function readStatement() {
    read.mutate(undefined, {
      onError: (error) => toast.error(errorMessage(error, 'Couldn’t start reading the statement.')),
    })
  }

  function confirmStatement() {
    confirm.mutate(undefined, {
      onSuccess: () => toast('Statement confirmed'),
      onError: (error) => toast.error(errorMessage(error, 'Couldn’t confirm the statement.')),
    })
  }

  return (
    <>
      {running && <JobProgress message={job?.message || 'Reading statement…'} progress={job?.progress ?? 0} />}

      <div className={cn(running && 'pointer-events-none opacity-50')} aria-busy={running}>
        {job?.status === 'failed' && (
          <Banner onRetry={readStatement} className="mb-4">
            {job.message}
          </Banner>
        )}
        {hasLines && check && !check.ok && (
          <Banner className="mb-4">
            <p className="font-medium">The statement can’t be confirmed.</p>
            <ul className="mt-1 list-disc pl-4">
              {check.problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </Banner>
        )}
        {confirmed && (
          <Banner tone="info" className="mb-4">
            <span className="font-medium text-stone-900">Statement confirmed</span>
            {view.confirmedAt && <> on {dateTime.format(new Date(view.confirmedAt))}</>}
            {view.confirmedBy && <> by {view.confirmedBy}</>}.
          </Banner>
        )}

        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatTile label="Lines read" value={hasLines ? String(check?.lines ?? view.lines.length) : '—'} />
          <StatTile
            label="Debits"
            value={check ? formatINR(check.debitsPaise) : '—'}
            check={check ? totalCheck(check.debitsOk, check.printedDebitsPaise, check.debitsDifferencePaise) : undefined}
          />
          <StatTile
            label="Credits"
            value={check ? formatINR(check.creditsPaise) : '—'}
            check={check ? totalCheck(check.creditsOk, check.printedCreditsPaise, check.creditsDifferencePaise) : undefined}
          />
          <StatTile label="Cards" value={check && check.cards.length > 0 ? check.cards.join(', ') : '—'} />
        </div>
        {hasLines && (
          <p className="mt-2 text-[12px] text-stone-500">
            Statement date {formatDate(view.statementDate)} · Period {formatDate(view.periodStart)} –{' '}
            {formatDate(view.periodEnd)}
          </p>
        )}

        <div className="mt-5 overflow-hidden rounded-md border border-stone-200 bg-white">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-stone-200 px-4 py-3">
            <span className="text-[13px] font-semibold">
              Statement lines{' '}
              <span className="ml-1 font-normal text-stone-500">{hasLines ? `${view.lines.length} lines` : ''}</span>
            </span>
            <div className="flex items-center gap-2">
              {hasLines && (
                <input
                  type="search"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Find SerNo or description"
                  aria-label="Find a statement line by serial number or description"
                  className="h-8 w-52 rounded-md border border-stone-300 bg-white px-2.5 text-[12px] outline-none placeholder:text-stone-400 focus-visible:ring-2 focus-visible:ring-teal-600/40"
                />
              )}
              {onReplace && (
                <Button variant="secondary" onClick={onReplace}>
                  Replace statement
                </Button>
              )}
              <Button variant="secondary" onClick={() => void openStoredFile(statementFileId)}>
                <Download />
                Download PDF
              </Button>
            </div>
          </div>

          {!hasLines ? (
            <div className="flex flex-col items-center justify-center gap-3 px-4 py-10 text-center">
              <div className="w-full max-w-[560px] text-left">{fileRow}</div>
              <p className="text-[13px] text-stone-500">The statement hasn’t been read yet.</p>
              <Button onClick={readStatement} disabled={running}>
                Read statement
              </Button>
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-left text-[12px]">
                  <thead className="bg-stone-50 text-[11px] font-medium uppercase tracking-wide text-stone-500">
                    <tr>
                      <th className="px-4 py-3">Date</th>
                      <th className="py-3">SerNo</th>
                      <th className="py-3">Description</th>
                      <th className="py-3">Card</th>
                      <th className="py-3">Foreign amount</th>
                      <th className="px-4 py-3 text-right">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lines.map((t) => (
                      <tr className="border-t border-stone-100 hover:bg-stone-50" key={t.id}>
                        <td className="px-4 py-3 tabular-nums">{formatDate(t.date)}</td>
                        <td className="tabular-nums text-stone-500">{t.serNo}</td>
                        <td>{t.description}</td>
                        <td className="text-stone-500">{t.cardLast4 ?? '—'}</td>
                        <td className="tabular-nums text-stone-500">
                          {t.foreign ? formatForeign(t.foreign.amountMinor, t.foreign.currency) : '—'}
                        </td>
                        <td className={cn('px-4 text-right font-medium tabular-nums', t.isCredit && 'text-red-700')}>
                          {formatINR(t.amountPaise, { credit: t.isCredit })}
                        </td>
                      </tr>
                    ))}
                    {lines.length === 0 && (
                      <tr>
                        <td colSpan={6} className="px-4 py-6 text-center text-stone-500">
                          No lines match “{search.trim()}”.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <p className="border-t border-stone-100 px-4 py-2 text-[11px] text-stone-400">
                Showing {lines.length} of {view.lines.length} lines
              </p>
            </>
          )}
        </div>

        {hasLines && (
          <div className="mt-5 flex justify-end gap-2">
            {!confirmed && (
              <Button variant="secondary" onClick={readStatement} disabled={running}>
                Read again
              </Button>
            )}
            {confirmed ? (
              <Button onClick={() => navigate(`/cycles/${cycleId}/invoices`)}>
                Continue to invoices <ChevronRight />
              </Button>
            ) : (
              <Button disabled={!check?.ok || running || confirm.isPending} onClick={confirmStatement}>
                {confirm.isPending ? 'Confirming…' : 'Confirm statement'} <ChevronRight />
              </Button>
            )}
          </div>
        )}
      </div>
    </>
  )
}

function totalCheck(ok: boolean, printed: number | null, difference: number | null) {
  if (printed === null) return { ok: false, text: 'statement total not found' }
  if (ok) return { ok: true, text: `matches statement ${formatINR(printed)}` }
  return {
    ok: false,
    text: `vs statement ${formatINR(printed)} · differs by ${formatINR(Math.abs(difference ?? 0))}`,
  }
}
