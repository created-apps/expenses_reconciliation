import { useQuery } from '@tanstack/react-query'

import { cycleKeys } from '@/api/cycles'
import { apiFetch } from '@/lib/api'
import type { AmazonGroup, GiftOrder } from '@/types'

type ReportDto = {
  file: { id: string; name: string; has_copy: boolean } | null
  rows: number
  unpaid_rows: number
  card_last4s: string[]
  payment_date_from: string | null
  payment_date_to: string | null
  groups: {
    payment_date: string | null
    reference: string
    card_last4: string | null
    orders: number
    amount_paise: number
  }[]
  gift: { paid_on: string | null; order_id: string | null; amount_paise: number }[]
}

/** The uploaded Amazon Business report; `file` is null when none was uploaded. Money in paise. */
export type AmazonReport = {
  file: { id: string; name: string; hasCopy: boolean } | null
  rows: number
  unpaidRows: number
  cardLast4s: string[]
  paymentDateFrom: string | null
  paymentDateTo: string | null
  groups: AmazonGroup[]
  gift: GiftOrder[]
}

function toReport(d: ReportDto): AmazonReport {
  return {
    file: d.file && { id: d.file.id, name: d.file.name, hasCopy: d.file.has_copy },
    rows: d.rows,
    unpaidRows: d.unpaid_rows,
    cardLast4s: d.card_last4s,
    paymentDateFrom: d.payment_date_from,
    paymentDateTo: d.payment_date_to,
    groups: d.groups.map((g) => ({
      paymentDate: g.payment_date,
      reference: g.reference,
      cardLast4: g.card_last4,
      orders: g.orders,
      amountPaise: g.amount_paise,
    })),
    gift: d.gift.map((g) => ({ date: g.paid_on, amountPaise: g.amount_paise })),
  }
}

export function useAmazonReport(cycleId: string) {
  return useQuery({
    queryKey: cycleKeys.amazon(cycleId),
    queryFn: async () => toReport(await apiFetch<ReportDto>(`/api/cycles/${cycleId}/amazon-report`)),
  })
}

// ---- Amazon invoices to fetch -------------------------------------------------------------------

type FetchDto = {
  has_report: boolean
  matched: boolean
  payment_date_from: string | null
  payment_date_to: string | null
  coverage: {
    card_orders: number
    with_invoice: number
    without_invoice: number
    partly_invoiced: number
    gift_orders: number
    gift_with_invoice: number
  } | null
  items: {
    order_id: string
    payment_date: string | null
    amount_paise: number
    group_reference: string
    transaction_id: string
    ser_no: string
    charge_date: string
    charge_amount_paise: number
    description: string
  }[]
  total_orders: number
  total_paise: number
  invoices_without_order_id: number
}

/** An Amazon order that has no invoice uploaded, and the statement charge it was paid in. Money in paise. */
export type FetchOrder = {
  orderId: string
  paymentDate: string | null
  amountPaise: number
  groupReference: string
  serNo: string
  chargeDate: string
  chargeAmountPaise: number
  description: string
}

export type AmazonFetch = {
  hasReport: boolean
  matched: boolean
  coverage: {
    cardOrders: number
    withInvoice: number
    withoutInvoice: number
    partlyInvoiced: number
    giftOrders: number
    giftWithInvoice: number
  } | null
  items: FetchOrder[]
  totalOrders: number
  totalPaise: number
  invoicesWithoutOrderId: number
}

function toFetch(d: FetchDto): AmazonFetch {
  const c = d.coverage
  return {
    hasReport: d.has_report,
    matched: d.matched,
    coverage: c && {
      cardOrders: c.card_orders,
      withInvoice: c.with_invoice,
      withoutInvoice: c.without_invoice,
      partlyInvoiced: c.partly_invoiced,
      giftOrders: c.gift_orders,
      giftWithInvoice: c.gift_with_invoice,
    },
    items: d.items.map((i) => ({
      orderId: i.order_id,
      paymentDate: i.payment_date,
      amountPaise: i.amount_paise,
      groupReference: i.group_reference,
      serNo: i.ser_no,
      chargeDate: i.charge_date,
      chargeAmountPaise: i.charge_amount_paise,
      description: i.description,
    })),
    totalOrders: d.total_orders,
    totalPaise: d.total_paise,
    invoicesWithoutOrderId: d.invoices_without_order_id,
  }
}

/** Orders of the report's payment groups (one per statement charge) that have no invoice file. */
export function useAmazonToFetch(cycleId: string, enabled = true) {
  return useQuery({
    queryKey: cycleKeys.amazonFetch(cycleId),
    queryFn: async () => toFetch(await apiFetch<FetchDto>(`/api/cycles/${cycleId}/amazon-to-fetch`)),
    enabled,
  })
}
