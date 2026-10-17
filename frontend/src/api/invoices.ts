import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { cycleKeys } from '@/api/cycles'
import { apiFetch } from '@/lib/api'
import type { ExtractionState } from '@/types'

// ---- Shapes as the API sends them (snake_case) --------------------------------------------------

type EntryDto = {
  key: string
  file_id: string
  file_name: string
  file_kind: string
  file_status: string
  file_note: string | null
  mime_type: string | null
  has_copy: boolean
  can_restore: boolean
  state: ExtractionState
  invoice_id: string | null
  block_index: number | null
  vendor_key: string | null
  vendor_name: string | null
  invoice_no: string | null
  order_id: string | null
  invoice_date: string | null
  order_date: string | null
  currency: 'INR' | 'USD' | null
  total_minor: number | null
  is_credit_note: boolean
  source: 'pdf_text' | 'vision' | 'manual' | null
  problems: string[]
  duplicate_of_name: string | null
}

type InvoicesDto = {
  status: string
  job: { status: 'running' | 'done' | 'failed'; progress: number | null; message: string | null } | null
  counts: {
    files: number
    unread: number
    invoices: number
    pending: number
    needs_check: number
    failed: number
    duplicate_files: number
    duplicate_invoices: number
    ignored: number
  }
  vendors: { key: string; name: string }[]
  entries: EntryDto[]
}

// ---- App shapes (money in minor units of the invoice's own currency; never floats) --------------

export type InvoiceEntry = {
  key: string
  fileId: string
  fileName: string
  fileKind: string
  fileStatus: string
  fileNote: string | null
  hasCopy: boolean
  canRestore: boolean // a file set aside with "Not an invoice" can be brought back
  state: ExtractionState
  invoiceId: string | null // null for files that have no invoice row (duplicate, ignored, unread...)
  blockIndex: number | null
  vendorKey: string | null
  vendorName: string | null
  invoiceNo: string | null
  orderId: string | null
  invoiceDate: string | null // ISO date
  orderDate: string | null
  currency: 'INR' | 'USD' | null
  totalMinor: number | null
  isCreditNote: boolean
  source: 'pdf_text' | 'vision' | 'manual' | null
  problems: string[]
  duplicateOfName: string | null
}

export type InvoiceCounts = {
  files: number
  unread: number
  invoices: number
  pending: number
  needsCheck: number
  failed: number
  duplicateFiles: number
  duplicateInvoices: number
  ignored: number
}

export type InvoicesView = {
  status: string
  job: { status: 'running' | 'done' | 'failed'; progress: number; message: string } | null
  counts: InvoiceCounts
  vendors: { key: string; name: string }[]
  entries: InvoiceEntry[]
}

/** What a person can correct. Only the fields present are sent; `null` clears a field. */
export type InvoiceChanges = Partial<{
  vendorKey: string | null
  invoiceNo: string | null
  orderId: string | null
  invoiceDate: string | null
  orderDate: string | null
  currency: 'INR' | 'USD'
  totalMinor: number | null
}>

const FIELD_NAMES: Record<keyof InvoiceChanges, string> = {
  vendorKey: 'vendor_key',
  invoiceNo: 'invoice_no',
  orderId: 'order_id',
  invoiceDate: 'invoice_date',
  orderDate: 'order_date',
  currency: 'currency',
  totalMinor: 'total_minor',
}

function toView(d: InvoicesDto): InvoicesView {
  const c = d.counts
  return {
    status: d.status,
    job: d.job && { status: d.job.status, progress: d.job.progress ?? 0, message: d.job.message ?? '' },
    counts: {
      files: c.files,
      unread: c.unread,
      invoices: c.invoices,
      pending: c.pending,
      needsCheck: c.needs_check,
      failed: c.failed,
      duplicateFiles: c.duplicate_files,
      duplicateInvoices: c.duplicate_invoices,
      ignored: c.ignored,
    },
    vendors: d.vendors,
    entries: d.entries.map((e) => ({
      key: e.key,
      fileId: e.file_id,
      fileName: e.file_name,
      fileKind: e.file_kind,
      fileStatus: e.file_status,
      fileNote: e.file_note,
      hasCopy: e.has_copy,
      canRestore: e.can_restore,
      state: e.state,
      invoiceId: e.invoice_id,
      blockIndex: e.block_index,
      vendorKey: e.vendor_key,
      vendorName: e.vendor_name,
      invoiceNo: e.invoice_no,
      orderId: e.order_id,
      invoiceDate: e.invoice_date,
      orderDate: e.order_date,
      currency: e.currency,
      totalMinor: e.total_minor,
      isCreditNote: e.is_credit_note,
      source: e.source,
      problems: e.problems,
      duplicateOfName: e.duplicate_of_name,
    })),
  }
}

// ---- Queries and mutations ----------------------------------------------------------------------

/** The invoice rows, their counts and the read job. Polls once a second while a read runs. */
export function useInvoices(cycleId: string) {
  return useQuery({
    queryKey: cycleKeys.invoices(cycleId),
    queryFn: async () => toView(await apiFetch<InvoicesDto>(`/api/cycles/${cycleId}/invoices`)),
    refetchInterval: (query) => (query.state.data?.job?.status === 'running' ? 1000 : false),
  })
}

export function useReadInvoices(cycleId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => toView(await apiFetch<InvoicesDto>(`/api/cycles/${cycleId}/invoices/extract`, { method: 'POST' })),
    onSuccess: (view) => {
      qc.setQueryData(cycleKeys.invoices(cycleId), view)
      void qc.invalidateQueries({ queryKey: cycleKeys.one(cycleId) }) // the first edit after an export moves the cycle back to matched
    },
  })
}

export function useCorrectInvoice(cycleId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ invoiceId, changes }: { invoiceId: string; changes: InvoiceChanges }) => {
      const body: Record<string, unknown> = {}
      for (const [key, value] of Object.entries(changes)) body[FIELD_NAMES[key as keyof InvoiceChanges]] = value
      return toView(
        await apiFetch<InvoicesDto>(`/api/invoices/${invoiceId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }),
      )
    },
    onSuccess: (view) => {
      qc.setQueryData(cycleKeys.invoices(cycleId), view)
      void qc.invalidateQueries({ queryKey: cycleKeys.one(cycleId) }) // the first edit after an export moves the cycle back to matched
    },
  })
}

export function useNotAnInvoice(cycleId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (invoiceId: string) =>
      toView(await apiFetch<InvoicesDto>(`/api/invoices/${invoiceId}/not-invoice`, { method: 'POST' })),
    onSuccess: (view) => {
      qc.setQueryData(cycleKeys.invoices(cycleId), view)
      void qc.invalidateQueries({ queryKey: cycleKeys.one(cycleId) }) // the first edit after an export moves the cycle back to matched
    },
  })
}

/** Brings back a file that was set aside with "Not an invoice"; "Read invoices" then reads it again. */
export function useRestoreFile(cycleId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (fileId: string) =>
      toView(await apiFetch<InvoicesDto>(`/api/files/${fileId}/restore`, { method: 'POST' })),
    onSuccess: (view) => {
      qc.setQueryData(cycleKeys.invoices(cycleId), view)
      void qc.invalidateQueries({ queryKey: cycleKeys.one(cycleId) }) // the first edit after an export moves the cycle back to matched
    },
  })
}
