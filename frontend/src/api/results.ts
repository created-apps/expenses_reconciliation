import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { cycleKeys } from '@/api/cycles'
import { apiFetch } from '@/lib/api'
import type { Status } from '@/types'

// ---- Shapes as the API sends them (snake_case) --------------------------------------------------

type InvoiceDto = {
  id: string
  file_id: string
  file_name: string
  vendor_key: string | null
  vendor_name: string | null
  invoice_no: string | null
  order_id: string | null
  invoice_date: string | null
  order_date: string | null
  currency: 'INR' | 'USD'
  total_minor: number | null
  is_credit_note: boolean
  needs_check: boolean
  linked_by: string | null
}

type LineDto = {
  id: string
  ser_no: string
  txn_date: string
  description: string
  card_last4: string | null
  vendor_key: string | null
  vendor_name: string | null
  foreign: { amount_minor: number; currency: string } | null
  amount_paise: number
  is_credit: boolean
  status: Status | null
  note: string
  updated_by: string | null
  updated_at: string | null
  invoices: InvoiceDto[]
  suggestions: InvoiceDto[]
  comparison: {
    attached_sum_paise: number
    difference_paise: number
    state: 'none' | 'matches' | 'differs'
    needs_note: boolean
    note_missing: boolean
  }
}

type LinesDto = {
  total: number
  shown: number
  vendors: { key: string; name: string }[]
  cards: string[]
  items: LineDto[]
}

type UnusedDto = { total: number; items: (InvoiceDto & { reason: string })[] }

// ---- App shapes (money in paise, or minor units of the invoice's own currency; never floats) ----

/** An invoice as attached to, suggested for, or searched for a statement line. Carries its OWN total. */
export type ResultInvoice = {
  id: string
  fileId: string
  fileName: string
  vendorKey: string | null
  vendorName: string | null
  invoiceNo: string | null
  orderId: string | null
  date: string | null // invoice date, else order date
  currency: 'INR' | 'USD'
  totalMinor: number | null
  isCreditNote: boolean
  needsCheck: boolean
  linkedBy: string | null // who attached it by hand; null when the system did
}

export type UnusedInvoice = ResultInvoice & { reason: string }

/** The sum of the attached invoices against the charge, worked out by the server (never in the browser). */
export type Comparison = {
  attachedSumPaise: number
  differencePaise: number // charge minus attached sum
  state: 'none' | 'matches' | 'differs'
  needsNote: boolean // invoices are attached and the difference is not zero
  noteMissing: boolean // ...and the note is still the system's own: saving is refused
}

export type ResultLine = {
  id: string
  serNo: string
  date: string // ISO
  description: string
  cardLast4: string | null
  vendorKey: string | null
  vendorName: string | null
  foreign: { amountMinor: number; currency: string } | null
  amountPaise: number // always positive; isCredit marks credits
  isCredit: boolean
  status: Status
  note: string
  updatedBy: string | null
  updatedAt: string | null
  invoices: ResultInvoice[]
  suggestions: ResultInvoice[]
  comparison: Comparison
}

export type LineFilters = { status?: Status; vendor?: string; card?: string; q?: string }

export type LinesView = {
  total: number
  shown: number
  vendors: { key: string; name: string }[]
  cards: string[]
  items: ResultLine[]
}

/** What a person does to one line; anything left out stays as it is. */
export type LineChanges = {
  attachInvoiceIds?: string[]
  detachInvoiceIds?: string[]
  status?: Status
  note?: string
}

function toInvoice(d: InvoiceDto): ResultInvoice {
  return {
    id: d.id,
    fileId: d.file_id,
    fileName: d.file_name,
    vendorKey: d.vendor_key,
    vendorName: d.vendor_name,
    invoiceNo: d.invoice_no,
    orderId: d.order_id,
    date: d.invoice_date ?? d.order_date,
    currency: d.currency,
    totalMinor: d.total_minor,
    isCreditNote: d.is_credit_note,
    needsCheck: d.needs_check,
    linkedBy: d.linked_by,
  }
}

function toLine(d: LineDto): ResultLine {
  return {
    id: d.id,
    serNo: d.ser_no,
    date: d.txn_date,
    description: d.description,
    cardLast4: d.card_last4,
    vendorKey: d.vendor_key,
    vendorName: d.vendor_name,
    foreign: d.foreign && { amountMinor: d.foreign.amount_minor, currency: d.foreign.currency },
    amountPaise: d.amount_paise,
    isCredit: d.is_credit,
    status: d.status ?? 'Missing invoice',
    note: d.note,
    updatedBy: d.updated_by,
    updatedAt: d.updated_at,
    invoices: d.invoices.map(toInvoice),
    suggestions: d.suggestions.map(toInvoice),
    comparison: {
      attachedSumPaise: d.comparison.attached_sum_paise,
      differencePaise: d.comparison.difference_paise,
      state: d.comparison.state,
      needsNote: d.comparison.needs_note,
      noteMissing: d.comparison.note_missing,
    },
  }
}

function query(params: Record<string, string | undefined>): string {
  const p = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) if (value) p.set(key, value)
  const text = p.toString()
  return text ? `?${text}` : ''
}

// ---- Queries and mutations ----------------------------------------------------------------------

/** The statement lines with their invoices, filtered on the server. Keeps the old rows while new ones load. */
export function useLines(cycleId: string, filters: LineFilters, enabled = true) {
  return useQuery({
    queryKey: [...cycleKeys.lines(cycleId), filters],
    queryFn: async (): Promise<LinesView> => {
      const d = await apiFetch<LinesDto>(`/api/cycles/${cycleId}/transactions${query(filters)}`)
      return { total: d.total, shown: d.shown, vendors: d.vendors, cards: d.cards, items: d.items.map(toLine) }
    },
    placeholderData: keepPreviousData,
    enabled,
  })
}

/** Read invoices that no line uses (and no Review suggestion reserves), each with the reason. */
export function useUnusedInvoices(cycleId: string, filters: { q?: string; vendor?: string } = {}, enabled = true) {
  return useQuery({
    queryKey: [...cycleKeys.unused(cycleId), filters],
    queryFn: async () => {
      const d = await apiFetch<UnusedDto>(`/api/cycles/${cycleId}/unused-invoices${query(filters)}`)
      return { total: d.total, items: d.items.map((i): UnusedInvoice => ({ ...toInvoice(i), reason: i.reason })) }
    },
    placeholderData: keepPreviousData,
    enabled,
  })
}

function resolveBody(changes: LineChanges, preview: boolean): string {
  return JSON.stringify({
    attach_invoice_ids: changes.attachInvoiceIds ?? [],
    detach_invoice_ids: changes.detachInvoiceIds ?? [],
    status: changes.status,
    note: changes.note,
    preview,
  })
}

async function postResolve(lineId: string, changes: LineChanges, preview: boolean): Promise<ResultLine> {
  return toLine(
    await apiFetch<LineDto>(`/api/transactions/${lineId}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: resolveBody(changes, preview),
    }),
  )
}

/** The line as it would be after these changes (nothing is written): its new sum and difference. */
export function previewLine(lineId: string, changes: LineChanges): Promise<ResultLine> {
  return postResolve(lineId, changes, true)
}

/** Saves the changes to one line (attach, detach, status, note). */
export function useResolveLine(cycleId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ lineId, changes }: { lineId: string; changes: LineChanges }) => postResolve(lineId, changes, false),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: cycleKeys.lines(cycleId) })
      void qc.invalidateQueries({ queryKey: cycleKeys.unused(cycleId) })
      void qc.invalidateQueries({ queryKey: cycleKeys.matching(cycleId) })
      // The first edit after an export moves the cycle back to matched: the banner and the stepper follow.
      void qc.invalidateQueries({ queryKey: cycleKeys.one(cycleId) })
      void qc.invalidateQueries({ queryKey: cycleKeys.export(cycleId) })
      void qc.invalidateQueries({ queryKey: cycleKeys.amazonFetch(cycleId) }) // a changed line may leave the list
      void qc.invalidateQueries({ queryKey: cycleKeys.all })
    },
  })
}
