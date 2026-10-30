import { FileText, Search, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'

import {
  previewLine,
  useResolveLine,
  useUnusedInvoices,
  type LineChanges,
  type ResultInvoice,
  type ResultLine,
} from '@/api/results'
import { DetailSheet } from '@/components/DetailSheet'
import { UploadForLine } from '@/components/UploadForLine'
import { Button } from '@/components/ui/button'
import { errorMessage } from '@/lib/api'
import { formatDate, formatForeign, formatINR } from '@/lib/format'
import { formatInvoiceTotal } from '@/lib/money'
import { useDebounced } from '@/lib/useDebounced'
import { cn } from '@/lib/utils'
import type { Status } from '@/types'

// What a person may set by hand. Reversed, Payment, Bank charge and Credit – manual come from the rules.
const MANUAL_STATUSES: Status[] = ['Matched', 'Review', 'Missing invoice', 'No invoice']

const fieldClass =
  'w-full rounded border border-stone-200 bg-white text-[12px] outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100'

export function TransactionSheet({
  line,
  cycleId,
  onClose,
}: {
  line: ResultLine | null
  cycleId: string
  onClose: () => void
}) {
  return (
    <DetailSheet
      open={line !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
      title="Transaction"
      description="Statement line details, attached invoices and status"
    >
      {line && <LineForm key={line.id} line={line} cycleId={cycleId} onClose={onClose} />}
    </DetailSheet>
  )
}

function InvoiceLine({ invoice, onRemove }: { invoice: ResultInvoice; onRemove?: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3 text-[12px]">
      <span className="flex min-w-0 items-center gap-2">
        <FileText className="size-4 shrink-0 text-stone-400" />
        <span className="truncate" title={invoice.fileName}>
          {invoice.fileName}
        </span>
      </span>
      <span className="flex shrink-0 items-center gap-2">
        {/* Each row shows the invoice's OWN total, not the charge (design.md section 5, item 5). */}
        <span className="tabular-nums text-stone-600">{formatInvoiceTotal(invoice)}</span>
        {onRemove && (
          <button
            type="button"
            aria-label={`Remove ${invoice.fileName}`}
            onClick={onRemove}
            className="rounded p-0.5 text-stone-400 outline-none hover:text-stone-700 focus-visible:ring-2 focus-visible:ring-teal-600/40"
          >
            <X className="size-4" />
          </button>
        )}
      </span>
    </div>
  )
}

function LineForm({
  line,
  cycleId,
  onClose,
}: {
  line: ResultLine
  cycleId: string
  onClose: () => void
}) {
  const resolve = useResolveLine(cycleId)
  // What the person has staged but not saved. The server works out what the line would then look like.
  const [attach, setAttach] = useState<ResultInvoice[]>([])
  const [detach, setDetach] = useState<string[]>([])
  const [status, setStatus] = useState<Status>(line.status)
  const [note, setNote] = useState(line.note)
  const [view, setView] = useState<ResultLine>(line)
  const [checking, setChecking] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [noteAsked, setNoteAsked] = useState(false)
  const [query, setQuery] = useState('')
  const search = useUnusedInvoices(cycleId, { q: useDebounced(query.trim(), 300) || undefined })

  const dirty = attach.length > 0 || detach.length > 0 || status !== line.status || note.trim() !== line.note.trim()
  const changesKey = JSON.stringify({
    attachInvoiceIds: attach.map((a) => a.id),
    detachInvoiceIds: detach,
    status,
    note,
  } satisfies LineChanges)
  const settledKey = useDebounced(changesKey, 450)
  const settling = changesKey !== settledKey // the server has not been asked about the latest change yet

  // Ask the server what the line would look like: its sum, difference and whether a note is needed.
  useEffect(() => {
    if (!dirty) {
      setView(line)
      setProblem(null)
      return
    }
    let stale = false
    setChecking(true)
    previewLine(line.id, JSON.parse(settledKey) as LineChanges)
      .then((next) => {
        if (stale) return
        setView(next)
        setProblem(null)
      })
      .catch((error: unknown) => {
        if (!stale) setProblem(errorMessage(error, 'Couldn’t check the change. Please try again.'))
      })
      .finally(() => {
        if (!stale) setChecking(false)
      })
    return () => {
      stale = true
    }
  }, [settledKey, dirty, line])

  const shownIds = useMemo(() => new Set(view.invoices.map((i) => i.id)), [view.invoices])
  const stagedIds = useMemo(() => new Set(attach.map((a) => a.id)), [attach])
  // A credit note can't be attached to a charge (the server refuses it), so it is not offered for one.
  const results = (search.data?.items ?? [])
    .filter((c) => !shownIds.has(c.id) && !stagedIds.has(c.id) && (line.isCredit || !c.isCreditNote))
    .slice(0, 6)

  const cmp = view.comparison
  const adds = cmp.state === 'matches'
  const showSuggestions = status === 'Review' && view.suggestions.length > 0
  const suggestionSum = view.suggestions.reduce((acc, s) => acc + (s.currency === 'INR' ? (s.totalMinor ?? 0) : 0), 0)
  const suggestionGap = line.amountPaise - suggestionSum
  // The invoice for a charge that is under review or has none can be uploaded right here.
  const canUpload = !line.isCredit && (line.status === 'Review' || line.status === 'Missing invoice')
  const statusOptions = Array.from(new Set<Status>([line.status, ...MANUAL_STATUSES]))

  const stage = (invoices: ResultInvoice[]) => {
    setAttach((prev) => [...prev, ...invoices.filter((i) => !prev.some((p) => p.id === i.id))])
    setDetach((prev) => prev.filter((id) => !invoices.some((i) => i.id === id)))
  }
  const remove = (invoice: ResultInvoice) => {
    if (stagedIds.has(invoice.id)) setAttach((prev) => prev.filter((p) => p.id !== invoice.id))
    else setDetach((prev) => [...prev, invoice.id])
  }

  function save() {
    if (cmp.noteMissing) {
      setNoteAsked(true)
      return
    }
    resolve.mutate(
      {
        lineId: line.id,
        changes: { attachInvoiceIds: attach.map((a) => a.id), detachInvoiceIds: detach, status, note },
      },
      {
        onSuccess: () => {
          toast('Saved')
          onClose()
        },
        onError: (error) => setProblem(errorMessage(error, 'Couldn’t save. Please try again.')),
      },
    )
  }

  const noteError = noteAsked && cmp.noteMissing ? 'Add a note to explain the difference before saving.' : null

  return (
    <>
      <div className="border-b border-stone-200 pb-4">
        <div className="text-[15px] font-semibold">{line.description}</div>
        {line.foreign && (
          <div className="mt-0.5 text-[12px] tabular-nums text-stone-400">
            {formatForeign(line.foreign.amountMinor, line.foreign.currency)}
          </div>
        )}
        <div className="mt-1 text-[12px] text-stone-500">
          <span className="tabular-nums">{formatDate(line.date)}</span> · {line.serNo}
          {line.cardLast4 && <> · card {line.cardLast4}</>}
          {line.vendorName && <> · {line.vendorName}</>}
        </div>
        <div className={cn('mt-3 text-[20px] font-semibold tabular-nums', line.isCredit && 'text-red-700')}>
          {formatINR(line.amountPaise, { credit: line.isCredit })}
        </div>
      </div>

      <section className="border-b border-stone-200 py-4">
        <h3 className="text-[12px] font-semibold">Why</h3>
        <p className="mt-2 text-[12px] text-stone-600">
          {line.note || 'This line was classified from the statement description and amount.'}
        </p>
      </section>

      {showSuggestions && (
        <section className="border-b border-stone-200 py-4">
          <h3 className="text-[12px] font-semibold">Suggested invoices</h3>
          <div className="mt-3 flex flex-col gap-2 rounded-md border border-stone-200 p-3">
            {view.suggestions.map((s) => (
              <InvoiceLine key={s.id} invoice={s} />
            ))}
          </div>
          <p className="mt-2 text-[12px] text-stone-500">
            {view.suggestions.length === 1 ? 'Closest invoice is ' : 'These invoices are '}
            <span className="tabular-nums">{formatINR(Math.abs(suggestionGap))}</span>
            {suggestionGap >= 0 ? ' less.' : ' more.'}
          </p>
          <div className="mt-3">
            <Button
              onClick={() => {
                stage(view.suggestions)
                setStatus('Matched')
              }}
            >
              Accept suggestion
            </Button>
          </div>
        </section>
      )}

      <section className="border-b border-stone-200 py-4">
        <div className="flex items-center justify-between">
          <h3 className="text-[12px] font-semibold">Attached invoices</h3>
          <span className={cn('text-[12px] font-semibold', adds ? 'text-emerald-700' : 'text-amber-700')}>
            {adds ? 'Matched' : cmp.state === 'differs' ? 'Doesn’t add up' : 'Needs invoice'}
          </span>
        </div>
        <div className={cn('transition-opacity', checking && 'opacity-50')} aria-busy={checking}>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <div className="rounded-md border border-stone-200 bg-stone-50 p-3">
              <div className="text-[10px] font-medium uppercase tracking-wide text-stone-500">Charge</div>
              <div className="mt-1 text-[15px] font-semibold tabular-nums text-stone-900">
                {formatINR(line.amountPaise, { credit: line.isCredit })}
              </div>
            </div>
            <div
              className={cn(
                'rounded-md border p-3',
                adds ? 'border-emerald-200 bg-emerald-50/60' : 'border-amber-200 bg-amber-50/60',
              )}
            >
              <div className="text-[10px] font-medium uppercase tracking-wide text-stone-500">Attached invoices</div>
              <div className="mt-1 text-[15px] font-semibold tabular-nums text-stone-900">
                {formatINR(cmp.attachedSumPaise)}
              </div>
            </div>
          </div>
          <div className="mt-2 flex items-center justify-between rounded bg-stone-50 px-3 py-2 text-[11px]">
            <span className="text-stone-500">Difference</span>
            <span className={cn('font-semibold tabular-nums', cmp.differencePaise === 0 ? 'text-emerald-700' : 'text-amber-700')}>
              {formatINR(cmp.differencePaise)}
            </span>
          </div>
        </div>
        {view.invoices.length > 0 ? (
          <div className="mt-3 flex flex-col gap-2">
            {view.invoices.map((invoice) => (
              <InvoiceLine key={invoice.id} invoice={invoice} onRemove={() => remove(invoice)} />
            ))}
          </div>
        ) : (
          <p className="mt-2 text-[12px] text-stone-500">No invoices attached.</p>
        )}
        {checking && <p className="mt-2 text-[11px] text-stone-400">Updating…</p>}
      </section>

      <section className="border-b border-stone-200 py-4">
        <h3 className="text-[12px] font-semibold">Find an invoice</h3>
        <div className="relative mt-2">
          <Search className="absolute left-2 top-2 size-4 text-stone-400" />
          <input
            aria-label="Search unused invoices"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className={cn(fieldClass, 'h-8 pl-7')}
            placeholder="Search unused invoices, for example: amazon 175"
          />
        </div>
        <div className="mt-3 flex flex-col gap-2">
          {results.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => stage([c])}
              className="flex w-full items-center justify-between gap-3 rounded border border-stone-200 px-3 py-2 text-left text-[12px] outline-none hover:bg-stone-50 focus-visible:ring-2 focus-visible:ring-teal-600/40"
            >
              <span className="min-w-0">
                <span className="block truncate">{c.fileName}</span>
                <span className="text-stone-500">
                  <span className="tabular-nums">{formatInvoiceTotal(c)}</span> · {formatDate(c.date)} ·{' '}
                  {c.vendorName ?? 'No vendor'}
                </span>
              </span>
              <span className="shrink-0 font-medium text-teal-700">Attach</span>
            </button>
          ))}
          {search.isError && <p className="text-[12px] text-red-700">Couldn’t search the invoices.</p>}
          {!search.isError && results.length === 0 && (
            <p className="text-[12px] text-stone-500">{search.isPending ? 'Searching…' : 'No unused invoices match.'}</p>
          )}
        </div>
      </section>

      {canUpload && (
        <section className="border-b border-stone-200 py-4">
          <h3 className="text-[12px] font-semibold">Don’t have it in the list?</h3>
          <UploadForLine
            cycleId={cycleId}
            isCredit={line.isCredit}
            onFound={(invoices) => {
              stage(invoices)
              setStatus('Matched')
            }}
          />
        </section>
      )}

      <section className="py-4">
        <label className="block text-[12px] font-medium">
          Status
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as Status)}
            className={cn(fieldClass, 'mt-1 h-8 px-2')}
          >
            {statusOptions.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
        <label className="mt-3 block text-[12px] font-medium">
          Note
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            aria-invalid={noteError !== null}
            className={cn(fieldClass, 'mt-1 min-h-16 p-2')}
          />
        </label>
        {cmp.noteMissing && !noteError && (
          <p className="mt-1 text-[12px] text-amber-700">The invoices don’t add up to the charge. Explain why in the note.</p>
        )}
        {noteError && (
          <p role="alert" className="mt-1 text-[12px] text-red-700">
            {noteError}
          </p>
        )}
        {problem && (
          <p role="alert" className="mt-2 text-[12px] text-red-700">
            {problem}
          </p>
        )}
        <div className="mt-4 flex justify-end">
          <Button onClick={save} disabled={!dirty || settling || checking || resolve.isPending || problem !== null}>
            {resolve.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
        {line.updatedBy && line.updatedAt && (
          <p className="mt-5 text-[11px] text-stone-400">
            Changed by {line.updatedBy} on {formatDate(line.updatedAt)}
          </p>
        )}
      </section>
    </>
  )
}
