import { Copy } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import type { AmazonFetch } from '@/api/amazon'
import { Banner } from '@/components/Banner'
import { EmptyState } from '@/components/EmptyState'
import { Button } from '@/components/ui/button'
import { formatDate, formatINR } from '@/lib/format'

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/**
 * "Amazon invoices to fetch": every order of the report's payment groups (one per statement charge) that has
 * no invoice uploaded, with the charge it was paid in. Needs the Amazon Business report and a matching run.
 */
export function AmazonFetchList({ data, cycleId }: { data: AmazonFetch; cycleId: string }) {
  const ids = data.items.map((i) => i.orderId)

  async function copyAll() {
    try {
      await navigator.clipboard.writeText(ids.join('\n'))
      toast(`Copied ${plural(ids.length, 'order ID')}`)
    } catch {
      toast.error('Couldn’t copy. Select the order IDs in the table and copy them by hand.')
    }
  }

  const c = data.coverage
  return (
    <>
      <p className="mb-3 text-[12px] text-stone-500">
        Orders in the Amazon Business report that were paid on a charge of this statement and have no invoice uploaded.
        Download these invoices from Amazon Business, use <b>Add files</b> on the Invoices step, then <b>Read invoices</b> and{' '}
        <b>Re-run matching</b>.
      </p>

      {data.invoicesWithoutOrderId > 0 && (
        <Banner tone="warning" className="mb-3">
          {plural(data.invoicesWithoutOrderId, 'Amazon invoice')} {data.invoicesWithoutOrderId === 1 ? 'has' : 'have'} no
          readable Order ID, so {data.invoicesWithoutOrderId === 1 ? 'its order' : 'their orders'} may be listed below even
          though the invoice is uploaded. Type the Order ID on the{' '}
          <Link to={`/cycles/${cycleId}/invoices`} className="font-medium underline">
            Invoices step
          </Link>{' '}
          (filter: Needs check).
        </Banner>
      )}

      {!data.matched ? (
        <EmptyState title="Run matching first." description="The list shows the orders of the charges matching has looked at." />
      ) : data.items.length === 0 ? (
        <EmptyState
          title="Every order has an invoice."
          description="All the orders in the report’s payment groups for this statement have an invoice uploaded."
        />
      ) : (
        <>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <span className="text-[13px] text-stone-700">
              <b>{plural(data.totalOrders, 'order')}</b> without an invoice · <span className="tabular-nums">{formatINR(data.totalPaise)}</span>
            </span>
            <Button variant="secondary" onClick={() => void copyAll()}>
              <Copy />
              Copy all IDs
            </Button>
          </div>
          <div className="overflow-x-auto rounded-md border border-stone-200 bg-white">
            <table className="w-full min-w-[640px] text-left text-[12px]">
              <thead className="bg-stone-50 text-[11px] font-medium uppercase tracking-wide text-stone-500">
                <tr>
                  <th className="px-4 py-3">Order ID</th>
                  <th className="py-3">Payment date</th>
                  <th className="py-3 text-right">Amount</th>
                  <th className="px-4 py-3">Charge</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((o) => (
                  <tr key={o.orderId} className="border-t border-stone-100 hover:bg-stone-50">
                    <td className="px-4 py-3 font-medium tabular-nums text-stone-800">{o.orderId}</td>
                    <td className="tabular-nums">{formatDate(o.paymentDate)}</td>
                    <td className="text-right tabular-nums">{formatINR(o.amountPaise)}</td>
                    <td className="px-4 text-stone-600">
                      <span className="tabular-nums">{formatDate(o.chargeDate)}</span> ·{' '}
                      <span className="tabular-nums">{formatINR(o.chargeAmountPaise)}</span> · {o.description}
                      <span className="ml-1 text-stone-400">({o.serNo})</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {c && (
        <p className="mt-3 text-[11px] text-stone-500">
          Whole report: {plural(c.cardOrders, 'card-paid order')}, {c.withInvoice} with an invoice, {c.withoutInvoice} without
          {c.partlyInvoiced > 0 && <> ({plural(c.partlyInvoiced, 'order')} with an invoice that covers only part of it: not listed)</>}.
          {c.giftOrders > 0 && (
            <> {plural(c.giftOrders, 'order')} paid from the gift balance (never on the card), {c.giftWithInvoice} with an invoice.</>
          )}
        </p>
      )}
    </>
  )
}
