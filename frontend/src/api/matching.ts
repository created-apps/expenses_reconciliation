import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { cycleKeys } from '@/api/cycles'
import { apiFetch } from '@/lib/api'
import type { Status } from '@/types'

type JobDto = { status: 'running' | 'done' | 'failed'; progress: number | null; message: string | null }

type SummaryDto = {
  ran: boolean
  total: number
  statuses: { status: Status; count: number; amount_paise: number }[]
  job: JobDto | null
}

/** Lines and signed amounts by status (credits negative), in paise. `ran` is false before the first run. */
export type MatchSummary = {
  ran: boolean
  total: number
  statuses: { status: Status; count: number; amountPaise: number }[]
  /** The matching run: running while it works, failed with a message, done when it has finished. */
  job: { status: 'running' | 'done' | 'failed'; progress: number; message: string } | null
}

function toSummary(d: SummaryDto): MatchSummary {
  return {
    ran: d.ran,
    total: d.total,
    statuses: d.statuses.map((s) => ({ status: s.status, count: s.count, amountPaise: s.amount_paise })),
    job: d.job && { status: d.job.status, progress: d.job.progress ?? 0, message: d.job.message ?? '' },
  }
}

/** The counts by status and the matching run. Polls once a second while a run is going. */
export function useMatchSummary(cycleId: string) {
  return useQuery({
    queryKey: cycleKeys.matching(cycleId),
    queryFn: async () => toSummary(await apiFetch<SummaryDto>(`/api/cycles/${cycleId}/match-summary`)),
    refetchInterval: (query) => (query.state.data?.job?.status === 'running' ? 1000 : false),
  })
}

/** Starts a matching run on the server (it works in the background; the summary above shows its progress). */
export function useRunMatching(cycleId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => toSummary(await apiFetch<SummaryDto>(`/api/cycles/${cycleId}/match`, { method: 'POST' })),
    onSuccess: (summary) => {
      qc.setQueryData(cycleKeys.matching(cycleId), summary)
      void qc.invalidateQueries({ queryKey: cycleKeys.one(cycleId) }) // an exported cycle goes back to matched
    },
  })
}

/** After a run has finished: everything that depends on the results is read again. */
export function refreshAfterMatching(qc: ReturnType<typeof useQueryClient>, cycleId: string) {
  void qc.invalidateQueries({ queryKey: cycleKeys.one(cycleId) })
  void qc.invalidateQueries({ queryKey: cycleKeys.all })
  void qc.invalidateQueries({ queryKey: cycleKeys.invoices(cycleId) })
  void qc.invalidateQueries({ queryKey: cycleKeys.lines(cycleId) })
  void qc.invalidateQueries({ queryKey: cycleKeys.unused(cycleId) })
  void qc.invalidateQueries({ queryKey: cycleKeys.export(cycleId) })
  void qc.invalidateQueries({ queryKey: cycleKeys.amazonFetch(cycleId) })
}

/** "65 matched, 5 to review" for the toast after a run. */
export function summarySentence(summary: MatchSummary): string {
  const count = (status: Status) => summary.statuses.find((s) => s.status === status)?.count ?? 0
  return `${count('Matched')} matched, ${count('Review')} to review`
}
