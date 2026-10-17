import { BADGE_COLORS, Pill } from '@/components/StatusBadge'
import type { CycleStatus } from '@/types'

const { GREEN, AMBER, SLATE_BLUE, STONE } = BADGE_COLORS

// design.md section 2, "Cycle status badges".
const CYCLE: Record<CycleStatus, { label: string; style: string }> = {
  draft: { label: 'Draft', style: STONE },
  statement_parsed: { label: 'Statement check', style: AMBER },
  statement_confirmed: { label: 'Invoices', style: SLATE_BLUE },
  invoices_extracted: { label: 'Invoices', style: SLATE_BLUE },
  matched: { label: 'Matched', style: GREEN },
  exported: { label: 'Exported', style: GREEN },
  failed: { label: 'Failed', style: 'bg-red-50 text-red-800' },
}

export function CycleStatusBadge({ status }: { status: CycleStatus }) {
  const { label, style } = CYCLE[status]
  return <Pill className={style}>{label}</Pill>
}
