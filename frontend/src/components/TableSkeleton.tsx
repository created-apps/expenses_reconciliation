/** Skeleton rows inside a table card (design.md section 5, item 7). */
export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="divide-y divide-stone-100" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-4 px-4 py-3">
          <div className="h-3 w-20 animate-pulse rounded bg-stone-100" />
          <div className="h-3 w-24 animate-pulse rounded bg-stone-100" />
          <div className="h-3 flex-1 animate-pulse rounded bg-stone-100" />
          <div className="h-3 w-16 animate-pulse rounded bg-stone-100" />
        </div>
      ))}
    </div>
  )
}
