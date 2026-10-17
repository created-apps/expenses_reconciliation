const MINUS = '−' // −, as in the design (credits are shown with a true minus sign)

const inr = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const inrWhole = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })

/**
 * Integer paise -> "₹1,05,980.00". Negative amounts, or `credit: true`, show as "−₹52,990.00".
 * Money is never a float here: the paise value is split into rupees and paise as integers.
 */
export function formatINR(paise: number, opts: { credit?: boolean } = {}): string {
  const negative = paise < 0 || opts.credit === true
  const abs = Math.abs(Math.trunc(paise))
  const rupees = Math.floor(abs / 100)
  const rest = abs % 100
  // Format the whole rupees with Indian grouping, then append the paise ourselves.
  const grouped = inr.format(rupees).replace(/\.00$/, '')
  return `${negative && abs !== 0 ? MINUS : ''}₹${grouped}.${String(rest).padStart(2, '0')}`
}

/** Whole-rupee summary, used by the status tiles: "₹5,41,727" (rounded to the nearest rupee). */
export function formatINRWhole(paise: number): string {
  const negative = paise < 0
  const rupees = Math.round(Math.abs(paise) / 100)
  return `${negative && rupees !== 0 ? MINUS : ''}₹${inrWhole.format(rupees)}`
}

/** Foreign minor units (cents) -> "$122.25"; other currencies get their code as a prefix. */
export function formatForeign(minor: number, currency: string): string {
  const abs = Math.abs(Math.trunc(minor))
  const text = `${Math.floor(abs / 100).toLocaleString('en-US')}.${String(abs % 100).padStart(2, '0')}`
  return currency === 'USD' ? `$${text}` : `${currency} ${text}`
}

/** Minor units -> plain decimal text for form fields: 5239000 -> "52390.00". Integer maths only. */
export function minorToDecimal(minor: number): string {
  const abs = Math.abs(Math.trunc(minor))
  return `${minor < 0 ? '-' : ''}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, '0')}`
}

/**
 * Text typed into a money field -> minor units, with integer maths only: "928.27" -> 92827,
 * "1,05,980" -> 10598000. Returns null when it is not a plain amount with at most two decimals.
 */
export function decimalToMinor(text: string): number | null {
  const match = /^(\d{1,10})(?:\.(\d{1,2}))?$/.exec(text.replace(/[,\s]/g, ''))
  if (!match) return null
  return Number(match[1]) * 100 + Number((match[2] ?? '').padEnd(2, '0'))
}

/** ISO date "2026-06-13" -> "13/06/2026". Returns "—" for empty or invalid input. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!match) return '—'
  return `${match[3]}/${match[2]}/${match[1]}`
}

/** Bytes -> "1.8 MB". */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
