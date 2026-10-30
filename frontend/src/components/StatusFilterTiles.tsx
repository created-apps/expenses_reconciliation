import { formatINRWhole } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { Status, StatusSummary } from '@/types'

export type StatusFilter = Status | 'All'

const NEEDS_ATTENTION: Status[] = ['Review', 'Missing invoice']

/**
 * The status filter tiles on the Results step, plus an "All" tile (v0 had no way to see every line).
 * Review and Missing invoice stay amber when inactive. When active they take the teal active
 * style plus an amber left border, so the two styles no longer clash (design.md section 6).
 */
export function StatusFilterTiles({
  summary,
  active,
  onChange,
  loading = false,
}: {
  summary: StatusSummary[]
  active: StatusFilter
  onChange: (value: StatusFilter) => void
  loading?: boolean
}) {
  const total = summary.reduce(
    (acc, s) => ({ count: acc.count + s.count, amountPaise: acc.amountPaise + s.amountPaise }),
    { count: 0, amountPaise: 0 },
  )
  const tiles: { key: StatusFilter; count: number; amountPaise: number }[] = [
    { key: 'All', ...total },
    ...summary.map((s) => ({ key: s.status as StatusFilter, count: s.count, amountPaise: s.amountPaise })),
  ]

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-5 xl:grid-cols-9" role="group" aria-label="Filter by status">
      {tiles.map((tile) => {
        const isActive = active === tile.key
        const amber = tile.key !== 'All' && NEEDS_ATTENTION.includes(tile.key)
        return (
          <button
            key={tile.key}
            type="button"
            aria-pressed={isActive}
            disabled={loading}
            onClick={() => onChange(tile.key)}
            className={cn(
              'rounded-md border px-2.5 py-2 text-left transition outline-none focus-visible:ring-2 focus-visible:ring-teal-600/40',
              isActive
                ? 'border-teal-700 bg-teal-50 ring-1 ring-teal-700/20'
                : amber
                  ? 'border-amber-300 bg-amber-50/70 hover:bg-amber-50'
                  : 'border-stone-200 bg-white hover:bg-stone-50',
              amber && isActive && 'border-l-2 border-l-amber-400',
            )}
          >
            <div className="flex items-start justify-between gap-1">
              <span
                className={cn(
                  'text-[11px] font-semibold leading-tight',
                  amber && !isActive ? 'text-amber-900' : 'text-stone-700',
                )}
              >
                {tile.key}
              </span>
              {loading ? (
                <span className="h-3 w-5 animate-pulse rounded bg-stone-100" />
              ) : (
                <span className="text-[11px] tabular-nums text-stone-500">{tile.count}</span>
              )}
            </div>
            {loading ? (
              <div className="mt-1.5 h-3 w-16 animate-pulse rounded bg-stone-100" />
            ) : (
              <div className="mt-1 text-[11px] tabular-nums text-stone-600">{formatINRWhole(tile.amountPaise)}</div>
            )}
          </button>
        )
      })}
    </div>
  )
}
