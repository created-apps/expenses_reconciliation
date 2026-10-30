import { formatForeign, formatINR } from '@/lib/format'

/** An invoice's own total, in its own currency: "₹928.27" or "$122.25". "—" when no total was read. */
export function formatInvoiceTotal(invoice: { currency: string; totalMinor: number | null }): string {
  if (invoice.totalMinor === null) return '—'
  return invoice.currency === 'INR' ? formatINR(invoice.totalMinor) : formatForeign(invoice.totalMinor, invoice.currency)
}
