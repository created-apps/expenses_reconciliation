import { Check } from 'lucide-react'

import { cn } from '@/lib/utils'

export type StepKey = 'statement' | 'invoices' | 'results' | 'export'

export const STEPS: { key: StepKey; label: string }[] = [
  { key: 'statement', label: 'Statement' },
  { key: 'invoices', label: 'Invoices' },
  { key: 'results', label: 'Results' },
  { key: 'export', label: 'Export' },
]

/**
 * Four steps. Done = filled teal circle with a check, current = teal outline, future = stone.
 * Connecting lines are teal when passed. Only steps up to `reachedIndex` can be clicked.
 */
export function Stepper({
  active,
  reachedIndex,
  onSelect,
}: {
  active: StepKey
  reachedIndex: number
  onSelect: (step: StepKey) => void
}) {
  const activeIndex = STEPS.findIndex((s) => s.key === active)
  return (
    <nav aria-label="Steps" className="mb-6 flex items-center gap-0 border-b border-stone-200 pb-5">
      {STEPS.map((step, i) => {
        const done = i < activeIndex
        const current = i === activeIndex
        const clickable = i <= reachedIndex && !current
        return (
          <div key={step.key} className="flex flex-1 items-center last:flex-none">
            <button
              type="button"
              disabled={!clickable}
              aria-current={current ? 'step' : undefined}
              onClick={() => onSelect(step.key)}
              className={cn(
                'flex items-center gap-2 rounded text-[12px] font-medium outline-none focus-visible:ring-2 focus-visible:ring-teal-600/40',
                done || current ? 'text-teal-800' : i <= reachedIndex ? 'text-stone-600' : 'text-stone-400',
                clickable ? 'cursor-pointer' : 'cursor-default',
              )}
            >
              <span
                className={cn(
                  'flex size-6 items-center justify-center rounded-full border text-[11px]',
                  done
                    ? 'border-teal-700 bg-teal-700 text-white'
                    : current
                      ? 'border-teal-700 text-teal-800'
                      : 'border-stone-300',
                )}
              >
                {done ? <Check className="size-3.5" /> : i + 1}
              </span>
              <span className="hidden sm:inline">{step.label}</span>
              <span className="sr-only sm:hidden">{step.label}</span>
            </button>
            {i < STEPS.length - 1 && (
              <div className={cn('mx-3 h-px flex-1', i < activeIndex ? 'bg-teal-700' : 'bg-stone-200')} />
            )}
          </div>
        )
      })}
    </nav>
  )
}
