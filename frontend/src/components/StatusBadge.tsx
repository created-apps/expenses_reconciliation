import { cn } from '@/lib/utils'
import type { ExtractionState, Status } from '@/types'

const PILL = 'inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap'

const GREEN = 'bg-[#e2efda] text-[#166534]'
const AMBER = 'bg-[#fff2cc] text-[#92400e]'
const ORANGE = 'bg-[#fce4d6] text-[#9a3412]'
const SLATE_BLUE = 'bg-[#e4eaf4] text-[#365277]'
const STONE = 'bg-stone-100 text-stone-700'
const STONE_QUIET = 'bg-stone-100 text-stone-600'

// design.md section 2, "Status badges". Status is always shown as text, never colour alone.
export const STATUS_STYLES: Record<Status, string> = {
  Matched: GREEN,
  Review: AMBER,
  'Missing invoice': ORANGE,
  'No invoice': STONE,
  Reversed: STONE_QUIET,
  'Credit – manual': SLATE_BLUE,
  Payment: STONE_QUIET,
  'Bank charge': STONE_QUIET,
}

export function Pill({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cn(PILL, className)}>{children}</span>
}

export function StatusBadge({ status }: { status: Status }) {
  return <Pill className={STATUS_STYLES[status]}>{status}</Pill>
}

const EXTRACTION: Record<ExtractionState, { label: string; style: string }> = {
  ok: { label: 'OK', style: GREEN },
  needs_check: { label: 'Needs check', style: AMBER },
  pending: { label: 'Waiting for AI', style: SLATE_BLUE },
  failed: { label: 'Failed', style: 'bg-red-50 text-red-800' },
  duplicate: { label: 'Duplicate', style: STONE },
  ignored: { label: 'Ignored', style: STONE },
  unread: { label: 'Not read yet', style: STONE_QUIET },
}

/** Status of an invoice file on the Invoices step. */
export function ExtractionBadge({ state }: { state: ExtractionState }) {
  const { label, style } = EXTRACTION[state]
  return <Pill className={style}>{label}</Pill>
}

export const BADGE_COLORS = { GREEN, AMBER, SLATE_BLUE, STONE }
