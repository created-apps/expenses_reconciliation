import { TriangleAlert } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const TONES = {
  // Mismatch and error banners (design.md section 5, items 2 and 9)
  error: 'border-red-200 bg-red-50 text-red-800',
  // Notices such as "5 lines still need review" (Export step)
  warning: 'border-amber-200 bg-[#fffaf0] text-amber-800',
  info: 'border-stone-200 bg-white text-stone-700',
}

export function Banner({
  tone = 'error',
  children,
  onRetry,
  className,
}: {
  tone?: keyof typeof TONES
  children: React.ReactNode
  /** When set, a Secondary "Retry" button is shown on the right (error banner). */
  onRetry?: () => void
  className?: string
}) {
  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      className={cn('flex items-start gap-2 rounded-md border p-3 text-[12px]', TONES[tone], className)}
    >
      {tone !== 'info' && <TriangleAlert className="mt-px size-4 shrink-0" />}
      <div className="min-w-0 flex-1">{children}</div>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry} className="-my-1 shrink-0">
          Retry
        </Button>
      )}
    </div>
  )
}
