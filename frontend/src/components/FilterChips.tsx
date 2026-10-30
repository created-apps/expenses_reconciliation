import { cn } from '@/lib/utils'

export type ChipOption<T extends string> = { value: T; label: string }

/** Pill filter chips (Invoices step): active is dark, inactive is light stone. */
export function FilterChips<T extends string>({
  options,
  value,
  onChange,
}: {
  options: ChipOption<T>[]
  value: T
  onChange: (value: T) => void
}) {
  return (
    <div className="flex flex-wrap gap-1" role="group" aria-label="Filter">
      {options.map((option) => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            className={cn(
              'rounded-full px-3 py-1.5 text-[12px] outline-none focus-visible:ring-2 focus-visible:ring-teal-600/40',
              active ? 'bg-stone-900 text-white' : 'bg-stone-100 text-stone-600 hover:bg-stone-200',
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
