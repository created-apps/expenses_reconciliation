// Domain types for the UI. They mirror the API shapes in doc/architecture.md section 5,
// with money as integer paise (INR) or minor units (foreign currency). Never floats.

export const STATUSES = [
  'Matched',
  'Review',
  'Missing invoice',
  'No invoice',
  'Reversed',
  'Credit – manual',
  'Payment',
  'Bank charge',
] as const

export type Status = (typeof STATUSES)[number]

export type CycleStatus =
  | 'draft'
  | 'statement_parsed'
  | 'statement_confirmed'
  | 'invoices_extracted'
  | 'matched'
  | 'exported'
  | 'failed'

export type Cycle = {
  id: string
  label: string | null // null until the statement is read (or a person names it)
  periodStart: string | null // ISO date, read from the statement PDF
  periodEnd: string | null
  status: CycleStatus
  matchedLines: number | null
  totalLines: number | null
  openItems: number | null
  createdAt: string // ISO date-time
  updatedAt: string // ISO date-time
}

/** What a row of the Invoices step is in: read fine, needs a person, waiting for the AI, and so on. */
export type ExtractionState = 'ok' | 'needs_check' | 'pending' | 'failed' | 'duplicate' | 'ignored' | 'unread'

export type StatusSummary = { status: Status; count: number; amountPaise: number }

/** One card charge in the Amazon Business report: the card-paid rows sharing a Payment Reference ID. */
export type AmazonGroup = {
  paymentDate: string | null // ISO date
  reference: string
  cardLast4: string | null
  orders: number // distinct orders in the group
  amountPaise: number
}

export type GiftOrder = { date: string | null; amountPaise: number }
