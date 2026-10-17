import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { cycleKeys } from '@/api/cycles'
import { apiBlob, apiFetch } from '@/lib/api'
import type { Status } from '@/types'

type SummaryDto = {
  sheet_name: string
  file_name: string
  sheets: string[]
  lines: number
  statuses: { status: Status; count: number; amount_paise: number }[]
  needs_review: number
  unused_invoices: number
  debits_paise: number
  printed_debits_paise: number | null
  debits_difference_paise: number | null
  credits_paise: number
  printed_credits_paise: number | null
  credits_difference_paise: number | null
  totals_ok: boolean
  last_exported_at: string | null
  edited_since_export: boolean
}

/** What the Export step shows. Money in paise; differences are lines minus what the statement prints. */
export type ExportSummary = {
  sheetName: string
  fileName: string
  sheets: string[]
  lines: number
  statuses: { status: Status; count: number; amountPaise: number }[]
  needsReview: number // Review plus Missing invoice
  unusedInvoices: number
  debitsPaise: number
  printedDebitsPaise: number | null
  debitsDifferencePaise: number | null
  creditsPaise: number
  printedCreditsPaise: number | null
  creditsDifferencePaise: number | null
  totalsOk: boolean
  lastExportedAt: string | null
  editedSinceExport: boolean
}

function toSummary(d: SummaryDto): ExportSummary {
  return {
    sheetName: d.sheet_name,
    fileName: d.file_name,
    sheets: d.sheets,
    lines: d.lines,
    statuses: d.statuses.map((s) => ({ status: s.status, count: s.count, amountPaise: s.amount_paise })),
    needsReview: d.needs_review,
    unusedInvoices: d.unused_invoices,
    debitsPaise: d.debits_paise,
    printedDebitsPaise: d.printed_debits_paise,
    debitsDifferencePaise: d.debits_difference_paise,
    creditsPaise: d.credits_paise,
    printedCreditsPaise: d.printed_credits_paise,
    creditsDifferencePaise: d.credits_difference_paise,
    totalsOk: d.totals_ok,
    lastExportedAt: d.last_exported_at,
    editedSinceExport: d.edited_since_export,
  }
}

export function useExportSummary(cycleId: string) {
  return useQuery({
    queryKey: cycleKeys.export(cycleId),
    queryFn: async () => toSummary(await apiFetch<SummaryDto>(`/api/cycles/${cycleId}/export-summary`)),
    retry: false, // 409 "Run matching first" is an answer, not a glitch
  })
}

/** Downloads the workbook for the current state. The server sets the cycle to `exported`. */
export function useDownloadExport(cycleId: string, fileName: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      const blob = await apiBlob(`/api/cycles/${cycleId}/export.xlsx`)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = fileName
      document.body.appendChild(link)
      link.click()
      link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 10_000)
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: cycleKeys.export(cycleId) })
      void qc.invalidateQueries({ queryKey: cycleKeys.one(cycleId) })
      void qc.invalidateQueries({ queryKey: cycleKeys.all })
    },
  })
}
