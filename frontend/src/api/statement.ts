import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { cycleKeys } from '@/api/cycles'
import { apiFetch } from '@/lib/api'
import type { CycleStatus } from '@/types'

// ---- Shapes as the API sends them (snake_case) --------------------------------------------------

type StatementDto = {
  status: CycleStatus
  statement_date: string | null
  period_start: string | null
  period_end: string | null
  summary: {
    previous_paise: number | null
    purchases_paise: number | null
    credits_paise: number | null
    total_due_paise: number | null
  }
  job: { status: 'running' | 'done' | 'failed'; progress: number | null; message: string | null } | null
  check: {
    lines: number
    debits_paise: number
    credits_paise: number
    printed_debits_paise: number | null
    printed_credits_paise: number | null
    debits_ok: boolean
    credits_ok: boolean
    debits_difference_paise: number | null
    credits_difference_paise: number | null
    cards: string[]
    ok: boolean
    problems: string[]
  } | null
  confirmed_at: string | null
  confirmed_by: string | null
  lines: {
    id: string
    ser_no: string
    txn_date: string
    description: string
    card_last4: string | null
    foreign_amount_minor: number | null
    foreign_currency: string | null
    amount_paise: number
    is_credit: boolean
  }[]
}

// ---- App shapes (money as integer paise; all checks are decided by the API) ----------------------

export type StatementLineRow = {
  id: string
  serNo: string
  date: string // ISO date
  description: string
  cardLast4: string | null
  foreign: { amountMinor: number; currency: string } | null
  amountPaise: number // always positive; isCredit marks credits
  isCredit: boolean
}

export type StatementCheck = {
  lines: number
  debitsPaise: number
  creditsPaise: number
  printedDebitsPaise: number | null
  printedCreditsPaise: number | null
  debitsOk: boolean
  creditsOk: boolean
  debitsDifferencePaise: number | null // lines read minus printed
  creditsDifferencePaise: number | null
  cards: string[]
  ok: boolean
  problems: string[]
}

export type StatementJob = { status: 'running' | 'done' | 'failed'; progress: number; message: string }

export type StatementView = {
  status: CycleStatus
  statementDate: string | null
  periodStart: string | null
  periodEnd: string | null
  job: StatementJob | null
  check: StatementCheck | null
  confirmedAt: string | null
  confirmedBy: string | null
  lines: StatementLineRow[]
}

function toView(d: StatementDto): StatementView {
  const c = d.check
  return {
    status: d.status,
    statementDate: d.statement_date,
    periodStart: d.period_start,
    periodEnd: d.period_end,
    job: d.job && { status: d.job.status, progress: d.job.progress ?? 0, message: d.job.message ?? '' },
    check: c && {
      lines: c.lines,
      debitsPaise: c.debits_paise,
      creditsPaise: c.credits_paise,
      printedDebitsPaise: c.printed_debits_paise,
      printedCreditsPaise: c.printed_credits_paise,
      debitsOk: c.debits_ok,
      creditsOk: c.credits_ok,
      debitsDifferencePaise: c.debits_difference_paise,
      creditsDifferencePaise: c.credits_difference_paise,
      cards: c.cards,
      ok: c.ok,
      problems: c.problems,
    },
    confirmedAt: d.confirmed_at,
    confirmedBy: d.confirmed_by,
    lines: d.lines.map((l) => ({
      id: l.id,
      serNo: l.ser_no,
      date: l.txn_date,
      description: l.description,
      cardLast4: l.card_last4,
      foreign:
        l.foreign_amount_minor !== null && l.foreign_currency
          ? { amountMinor: l.foreign_amount_minor, currency: l.foreign_currency }
          : null,
      amountPaise: l.amount_paise,
      isCredit: l.is_credit,
    })),
  }
}

// ---- Queries and mutations ----------------------------------------------------------------------

/** The statement's lines, header, totals check and job state. Polls once a second while a read runs. */
export function useStatement(cycleId: string) {
  return useQuery({
    queryKey: cycleKeys.statement(cycleId),
    queryFn: async () => toView(await apiFetch<StatementDto>(`/api/cycles/${cycleId}/statement`)),
    refetchInterval: (query) => (query.state.data?.job?.status === 'running' ? 1000 : false),
  })
}

export function useReadStatement(cycleId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => toView(await apiFetch<StatementDto>(`/api/cycles/${cycleId}/statement/parse`, { method: 'POST' })),
    onSuccess: (view) => qc.setQueryData(cycleKeys.statement(cycleId), view),
  })
}

export function useConfirmStatement(cycleId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => toView(await apiFetch<StatementDto>(`/api/cycles/${cycleId}/statement/confirm`, { method: 'POST' })),
    onSuccess: (view) => {
      qc.setQueryData(cycleKeys.statement(cycleId), view)
      void qc.invalidateQueries({ queryKey: cycleKeys.one(cycleId) })
      void qc.invalidateQueries({ queryKey: cycleKeys.all })
    },
  })
}
