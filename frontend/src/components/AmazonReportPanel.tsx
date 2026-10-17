import { ChevronDown } from 'lucide-react'
import { useId, useState } from 'react'

import { openStoredFile } from '@/api/cycles'
import type { AmazonReport } from '@/api/amazon'
import { formatDate, formatINR } from '@/lib/format'
import { cn } from '@/lib/utils'

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** Collapsible Amazon Business report card (design.md section 5, item 3), from the uploaded report. */
export function AmazonReportPanel({ report }: { report: AmazonReport }) {
  const [open, setOpen] = useState(true)
  const panelId = useId()
  const { file, groups, gift } = report
  return (
    <section className="mt-4 rounded-md border border-stone-200 bg-white">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between rounded-md px-4 py-3 text-left outline-none focus-visible:ring-2 focus-visible:ring-teal-600/40"
      >
        <span className="text-[13px] font-semibold text-stone-900">
          Amazon Business report · {plural(groups.length, 'payment group')}
        </span>
        <ChevronDown className={cn('size-4 text-stone-400 transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div id={panelId} className="border-t border-stone-200">
          <p className="px-4 py-3 text-[12px] text-stone-600">
            <b>{report.rows} rows</b> read
            {file && (
              <>
                {' '}
                from{' '}
                <button
                  type="button"
                  disabled={!file.hasCopy}
                  onClick={() => void openStoredFile(file.id)}
                  className="rounded font-medium text-teal-700 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-teal-600/40"
                >
                  {file.name}
                </button>
              </>
            )}
            {report.cardLast4s.length > 0 && <> · card {report.cardLast4s.map((c) => `•••• ${c}`).join(', ')}</>}
            {report.paymentDateFrom && report.paymentDateTo && (
              <>
                {' '}
                · payments {formatDate(report.paymentDateFrom)} – {formatDate(report.paymentDateTo)}
              </>
            )}
            {report.unpaidRows > 0 && (
              <span className="block text-[11px] text-stone-400">
                {plural(report.unpaidRows, 'row')} with no payment (not paid or not shipped) are left out.
              </span>
            )}
          </p>
          <div className="overflow-x-auto border-t border-stone-100">
            <table className="w-full min-w-[520px] text-left text-[12px]">
              <thead className="bg-stone-50 text-[11px] font-medium uppercase tracking-wide text-stone-500">
                <tr>
                  <th className="px-4 py-3">Payment date</th>
                  <th className="py-3">Card</th>
                  <th className="py-3">Reference</th>
                  <th className="py-3 text-right">Orders</th>
                  <th className="px-4 py-3 text-right">Amount</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((g) => (
                  <tr key={g.reference} className="border-t border-stone-100">
                    <td className="px-4 py-2.5 tabular-nums">{formatDate(g.paymentDate)}</td>
                    <td className="tabular-nums text-stone-600">{g.cardLast4 ? `•••• ${g.cardLast4}` : '—'}</td>
                    <td className="text-stone-600">{g.reference}</td>
                    <td className="text-right tabular-nums">{g.orders}</td>
                    <td className="px-4 text-right tabular-nums">{formatINR(g.amountPaise)}</td>
                  </tr>
                ))}
                {groups.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-4 text-center text-stone-500">
                      No card payments in this report.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="border-t border-stone-100 px-4 py-3">
            <h3 className="text-[12px] font-semibold text-stone-900">
              Paid by gift balance (not on the card): {plural(gift.length, 'order')}
            </h3>
            {gift.length > 0 && (
              <ul className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[12px] text-stone-600">
                {gift.map((g, i) => (
                  <li key={`${g.date}-${g.amountPaise}-${i}`} className="tabular-nums">
                    {formatDate(g.date)} · {formatINR(g.amountPaise)}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

/** Shown instead of the panel when no CSV was uploaded. */
export function NoAmazonReport() {
  return (
    <p className="mt-3 text-[12px] text-stone-500">
      No Amazon report uploaded. Amazon charges are matched on invoice totals only.
    </p>
  )
}
