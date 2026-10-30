import { useQueryClient } from '@tanstack/react-query'
import { ChevronDown, RefreshCw, Search } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useOutletContext, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'

import { refreshAfterMatching, useMatchSummary, useRunMatching } from '@/api/matching'
import { useAmazonToFetch } from '@/api/amazon'
import { useLines, useUnusedInvoices, type ResultLine } from '@/api/results'
import { AmazonFetchList } from '@/components/AmazonFetchList'
import { Banner } from '@/components/Banner'
import { EmptyState } from '@/components/EmptyState'
import { JobProgress } from '@/components/JobProgress'
import { KbdHint } from '@/components/KbdHint'
import { StatusBadge } from '@/components/StatusBadge'
import { StatusFilterTiles, type StatusFilter } from '@/components/StatusFilterTiles'
import { TableSkeleton } from '@/components/TableSkeleton'
import { TransactionSheet } from '@/components/TransactionSheet'
import { Button } from '@/components/ui/button'
import { errorMessage } from '@/lib/api'
import { formatDate, formatForeign, formatINR } from '@/lib/format'
import { formatInvoiceTotal } from '@/lib/money'
import { useDebounced } from '@/lib/useDebounced'
import { cn } from '@/lib/utils'
import type { CycleContext } from '@/pages/CycleLayout'
import type { StatusSummary } from '@/types'

/** Review if any line needs review, otherwise Missing invoice, otherwise All (design.md section 6). */
function defaultFilter(summary: StatusSummary[]): StatusFilter {
  const count = (status: string) => summary.find((s) => s.status === status)?.count ?? 0
  if (count('Review') > 0) return 'Review'
  if (count('Missing invoice') > 0) return 'Missing invoice'
  return 'All'
}

function ToolbarSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
}) {
  return (
    <label className="relative">
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 appearance-none rounded-md border border-stone-200 bg-white pl-3 pr-8 text-[12px] text-stone-600 outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
      >
        <option value="">{label}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 top-2.5 size-4 text-stone-400" />
    </label>
  )
}

/**
 * Results step: the outcome of matching by status, every statement line with its invoices, the review
 * drawer, and the invoices no line used. Everything shown comes from the server; the matching itself
 * runs there as a background job whose progress is shown here.
 */
export default function ResultsStep() {
  const { cycle } = useOutletContext<CycleContext>()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const wanted = params.get('tab')
  const summaryQuery = useMatchSummary(cycle.id)
  const rerun = useRunMatching(cycle.id)

  const summary = summaryQuery.data
  const job = summary?.job ?? null
  const running = job?.status === 'running' || rerun.isPending

  // When a run finishes while this page is open: say so, and read everything that depends on it again.
  const wasRunning = useRef(false)
  useEffect(() => {
    const now = job?.status === 'running'
    if (wasRunning.current && !now && job?.status === 'done') {
      toast(job.message)
      refreshAfterMatching(qc, cycle.id)
    }
    wasRunning.current = now
  }, [job, qc, cycle.id])

  const [filter, setFilter] = useState<StatusFilter | null>(null)
  const [query, setQuery] = useState('')
  const [unusedQuery, setUnusedQuery] = useState('')
  const [vendor, setVendor] = useState('')
  const [card, setCard] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [cursor, setCursor] = useState(0)

  // The first time results exist, start on the first filter that has something to do.
  useEffect(() => {
    if (filter === null && summary?.ran) setFilter(defaultFilter(summary.statuses))
  }, [filter, summary])

  const ready = Boolean(summary?.ran) && filter !== null
  const q = useDebounced(query.trim(), 300)
  const lines = useLines(
    cycle.id,
    { status: filter && filter !== 'All' ? filter : undefined, vendor: vendor || undefined, card: card || undefined, q: q || undefined },
    ready,
  )
  const unusedQ = useDebounced(unusedQuery.trim(), 300)
  const unused = useUnusedInvoices(cycle.id, { q: unusedQ || undefined }, Boolean(summary?.ran))
  const amazonFetch = useAmazonToFetch(cycle.id, Boolean(summary?.ran))
  // The Amazon tab exists only when a report was uploaded.
  const hasAmazonTab = amazonFetch.data?.hasReport === true
  const tab: 'lines' | 'unused' | 'amazon' =
    wanted === 'unused' ? 'unused' : wanted === 'amazon' && hasAmazonTab ? 'amazon' : 'lines'

  const rows: ResultLine[] = lines.data?.items ?? []
  const selected = rows.find((t) => t.id === selectedId) ?? null
  const safeCursor = Math.min(cursor, Math.max(rows.length - 1, 0))

  // j / k move, Enter opens. Ignored while typing in a field or while the drawer is open.
  // (Esc belongs to the drawer itself: the shadcn Sheet closes on Escape.)
  useEffect(() => {
    if (tab !== 'lines') return
    const onKeyDown = (event: KeyboardEvent) => {
      if (selectedId !== null || event.metaKey || event.ctrlKey || event.altKey) return
      const target = event.target as HTMLElement | null
      if (target && (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable)) return
      if (event.key === 'j') {
        event.preventDefault()
        setCursor(Math.min(safeCursor + 1, Math.max(rows.length - 1, 0)))
      } else if (event.key === 'k') {
        event.preventDefault()
        setCursor(Math.max(safeCursor - 1, 0))
      } else if (event.key === 'Enter' && rows[safeCursor] && target?.tagName !== 'BUTTON') {
        event.preventDefault()
        setSelectedId(rows[safeCursor].id)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [tab, selectedId, safeCursor, rows])

  function runAgain() {
    rerun.mutate(undefined, {
      onError: (error) => toast.error(errorMessage(error, 'Couldn’t start the matching. Please try again.')),
    })
  }

  const setTab = (next: 'lines' | 'unused' | 'amazon') =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev)
        if (next === 'lines') p.delete('tab')
        else p.set('tab', next)
        return p
      },
      { replace: true },
    )

  if (summaryQuery.isError) {
    return <Banner onRetry={() => void summaryQuery.refetch()}>{errorMessage(summaryQuery.error, 'Couldn’t load the results.')}</Banner>
  }
  if (!summary) {
    return <div className="h-24 animate-pulse rounded-md bg-stone-100" aria-busy="true" aria-label="Loading" />
  }

  if (!summary.ran) {
    return (
      <>
        {job?.status === 'running' && <JobProgress message={job.message} progress={job.progress} />}
        {job?.status === 'failed' && (
          <Banner onRetry={runAgain} className="mb-4">
            {job.message}
          </Banner>
        )}
        {job?.status !== 'running' && (
          <EmptyState
            title="No results yet."
            description="Matching has not run for this reconciliation."
            action={
              <Link to={`/cycles/${cycle.id}/invoices`} className="text-[13px] font-medium text-teal-700 hover:underline">
                Go to Invoices
              </Link>
            }
          />
        )}
      </>
    )
  }

  const unusedTotal = unused.data?.total
  const vendorOptions = (lines.data?.vendors ?? []).map((v) => ({ value: v.key, label: v.name }))
  const cardOptions = (lines.data?.cards ?? []).map((c) => ({ value: c, label: `Card ${c}` }))

  return (
    <>
      {running && <JobProgress message={job?.message || 'Matching…'} progress={job?.progress ?? 0} />}

      <div className={cn(running && 'pointer-events-none opacity-50')} aria-busy={running}>
        {job?.status === 'failed' && (
          <Banner onRetry={runAgain} className="mb-4">
            {job.message}
          </Banner>
        )}

        <div role="tablist" aria-label="Results" className="mb-4 flex gap-5 border-b border-stone-200">
          {(
            [
              ['lines', 'Statement lines'],
              ['unused', `Invoices not used${unusedTotal === undefined ? '' : ` (${unusedTotal})`}`],
              ...(hasAmazonTab
                ? ([['amazon', `Amazon invoices to fetch${amazonFetch.data?.matched ? ` (${amazonFetch.data.totalOrders})` : ''}`]] as const)
                : []),
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={cn(
                '-mb-px border-b-2 pb-2 text-[13px] outline-none focus-visible:ring-2 focus-visible:ring-teal-600/40',
                tab === key
                  ? 'border-teal-600 font-medium text-teal-800'
                  : 'border-transparent text-stone-500 hover:text-stone-800',
              )}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === 'lines' ? (
          <>
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h2 className="text-[14px] font-semibold text-stone-900">Results</h2>
                <p className="mt-0.5 text-[12px] text-stone-500">Resolve the items that need your attention first.</p>
              </div>
              <KbdHint />
            </div>

            <StatusFilterTiles
              summary={summary.statuses}
              active={filter ?? 'All'}
              onChange={(f) => {
                setFilter(f)
                setCursor(0)
              }}
            />

            <div className="mt-5 flex flex-wrap items-center gap-2">
              <div className="relative min-w-[200px] flex-1">
                <Search className="absolute left-2.5 top-2.5 size-4 text-stone-400" />
                <input
                  aria-label="Search"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value)
                    setCursor(0)
                  }}
                  placeholder="Search description, amount, file name"
                  className="h-9 w-full rounded-md border border-stone-200 bg-white pl-8 pr-3 text-[12px] outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
                />
              </div>
              <ToolbarSelect label="Vendor" value={vendor} options={vendorOptions} onChange={setVendor} />
              <ToolbarSelect label="Card" value={card} options={cardOptions} onChange={setCard} />
              <Button variant="secondary" onClick={runAgain} disabled={running}>
                <RefreshCw />
                Re-run matching
              </Button>
              <Button onClick={() => navigate(`/cycles/${cycle.id}/export`)} disabled={running}>
                Continue to export
              </Button>
            </div>

            {lines.isError ? (
              <Banner onRetry={() => void lines.refetch()} className="mt-4">
                {errorMessage(lines.error, 'Couldn’t load the statement lines.')}
              </Banner>
            ) : (
              <div className={cn('mt-4 overflow-x-auto rounded-md border border-stone-200 bg-white', lines.isFetching && !lines.isPending && 'opacity-70')}>
                {lines.isPending ? (
                  <TableSkeleton />
                ) : (
                  <table className="w-full min-w-[760px] table-fixed text-left text-[12px]">
                    <thead className="bg-stone-50 text-[11px] font-medium uppercase tracking-wide text-stone-500">
                      <tr>
                        <th className="w-[9%] px-4 py-3">Date</th>
                        <th className="w-[14%] py-3 pl-3">Transaction ID</th>
                        <th className="w-[22%] py-3">Description</th>
                        <th className="w-[12%] py-3 text-right">Amount</th>
                        <th className="w-[20%] px-2 py-3">Invoice files</th>
                        <th className="w-[12%] py-3">Status</th>
                        <th className="w-[11%] py-3">Notes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((t, i) => (
                        <tr
                          key={t.id}
                          onClick={() => {
                            setCursor(i)
                            setSelectedId(t.id)
                          }}
                          aria-selected={i === safeCursor}
                          className={cn(
                            'cursor-pointer border-t border-stone-100 hover:bg-stone-50',
                            i === safeCursor && 'bg-stone-50 shadow-[inset_2px_0_0_#0f766e]',
                          )}
                        >
                          <td className="px-4 py-3 tabular-nums">{formatDate(t.date)}</td>
                          <td className="pl-3 tabular-nums text-stone-500">{t.serNo}</td>
                          <td className="truncate pr-2 font-medium text-stone-800">
                            {t.description}
                            {t.foreign && (
                              <div className="font-normal text-stone-400">
                                {formatForeign(t.foreign.amountMinor, t.foreign.currency)}
                              </div>
                            )}
                          </td>
                          <td className={cn('pr-3 text-right font-medium tabular-nums', t.isCredit && 'text-red-700')}>
                            {formatINR(t.amountPaise, { credit: t.isCredit })}
                          </td>
                          <td className="px-2">
                            {t.invoices.length > 0 ? (
                              <div className="flex items-center gap-1">
                                <span className="max-w-[125px] truncate rounded border border-stone-200 bg-stone-50 px-1.5 py-0.5 text-[10px]">
                                  {t.invoices[0].fileName}
                                </span>
                                {t.invoices.length > 1 && <span className="text-stone-500">+{t.invoices.length - 1}</span>}
                              </div>
                            ) : (
                              <span className="text-stone-400">—</span>
                            )}
                          </td>
                          <td>
                            <StatusBadge status={t.status} />
                          </td>
                          <td className="truncate pr-3 text-stone-500" title={t.note}>
                            {t.note || '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}

            {lines.isSuccess && rows.length === 0 && (
              <div className="mt-4">
                {filter === 'Review' || filter === 'Missing invoice' ? (
                  <EmptyState title="Nothing needs review." description="This filter is clear for now." />
                ) : (
                  <EmptyState title="No lines match." description="Change the filter or the search." />
                )}
              </div>
            )}
            {lines.isSuccess && (
              <p className="mt-2 text-[11px] text-stone-400">
                Showing {lines.data.shown} of {lines.data.total} lines.
              </p>
            )}
          </>
        ) : tab === 'unused' ? (
          <>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <p className="text-[12px] text-stone-500">
                Invoices that no statement line used. A Review suggestion keeps its invoices out of this list.
              </p>
              <div className="relative min-w-[220px]">
                <Search className="absolute left-2.5 top-2.5 size-4 text-stone-400" />
                <input
                  aria-label="Search unused invoices"
                  value={unusedQuery}
                  onChange={(e) => setUnusedQuery(e.target.value)}
                  placeholder="Search file, vendor, amount"
                  className="h-9 w-full rounded-md border border-stone-200 bg-white pl-8 pr-3 text-[12px] outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
                />
              </div>
            </div>
            {unused.isError ? (
              <Banner onRetry={() => void unused.refetch()}>{errorMessage(unused.error, 'Couldn’t load the unused invoices.')}</Banner>
            ) : (
              <div className="overflow-x-auto rounded-md border border-stone-200 bg-white">
                {unused.isPending ? (
                  <TableSkeleton />
                ) : unused.data.items.length === 0 ? (
                  <div className="p-4">
                    <EmptyState title={unusedQuery ? 'No unused invoice matches.' : 'Every invoice was used.'} />
                  </div>
                ) : (
                  <table className="w-full min-w-[640px] text-left text-[12px]">
                    <thead className="bg-stone-50 text-[11px] font-medium uppercase tracking-wide text-stone-500">
                      <tr>
                        <th className="px-4 py-3">File</th>
                        <th className="py-3">Vendor</th>
                        <th className="py-3">Date</th>
                        <th className="py-3 text-right">Amount</th>
                        <th className="px-4 py-3">Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {unused.data.items.map((u) => (
                        <tr key={u.id} className="border-t border-stone-100 hover:bg-stone-50">
                          <td className="px-4 py-3 font-medium text-stone-800">{u.fileName}</td>
                          <td>{u.vendorName ?? <span className="text-amber-700">No vendor</span>}</td>
                          <td className="tabular-nums">{formatDate(u.date)}</td>
                          <td className="text-right tabular-nums">
                            {formatInvoiceTotal(u)}
                            {u.isCreditNote && <span className="ml-1 text-[11px] text-stone-400">credit</span>}
                          </td>
                          <td className="px-4 text-stone-500">{u.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </>
        ) : amazonFetch.isError ? (
          <Banner onRetry={() => void amazonFetch.refetch()}>
            {errorMessage(amazonFetch.error, 'Couldn’t load the Amazon invoices to fetch.')}
          </Banner>
        ) : amazonFetch.data ? (
          <AmazonFetchList data={amazonFetch.data} cycleId={cycle.id} />
        ) : (
          <TableSkeleton />
        )}
      </div>

      <TransactionSheet line={selected} cycleId={cycle.id} onClose={() => setSelectedId(null)} />
    </>
  )
}
