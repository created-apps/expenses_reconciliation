import { Check, X } from 'lucide-react'

import { cn } from '@/lib/utils'

export type StatCheck = { ok: boolean; text: string }

/** One of the four tiles on the Statement step. `loading` shows grey bars instead of values. */
export function StatTile({
  label,
  value,
  check,
  loading = false,
}: {
  label: string
  value: string
  check?: StatCheck
  loading?: boolean
}) {
  return (
    <div className="rounded-md border border-stone-200 bg-white p-4">
      <div className="text-[11px] uppercase tracking-wide text-stone-500">{label}</div>
      {loading ? (
        <>
          <div className="mt-2 h-5 w-28 animate-pulse rounded bg-stone-100" />
          <div className="mt-2 h-3 w-36 animate-pulse rounded bg-stone-100" />
        </>
      ) : (
        <>
          <div className="mt-2 text-[16px] font-semibold tabular-nums text-stone-900">{value}</div>
          {check && (
            <div
              className={cn(
                'mt-1 flex items-center gap-1 text-[11px]',
                check.ok ? 'text-emerald-700' : 'text-red-700',
              )}
            >
              {check.ok ? <Check className="size-3" /> : <X className="size-3" />}
              {check.text}
            </div>
          )}
        </>
      )}
    </div>
  )
}
