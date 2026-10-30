import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'

/**
 * Right-hand drawer (design.md section 3): 560px wide, full width at 900px or below,
 * `p-6`. Built on the shadcn Sheet, so it traps focus and closes on Esc.
 */
export function DetailSheet({
  open,
  onOpenChange,
  title,
  description,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: string
  children: React.ReactNode
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="gap-0 overflow-y-auto bg-white p-6 shadow-xl data-[side=right]:w-full data-[side=right]:sm:max-w-none data-[side=right]:min-[901px]:w-[560px] data-[side=right]:min-[901px]:max-w-[92vw]"
      >
        <SheetTitle className="pr-8 text-[16px] font-semibold text-stone-900">{title}</SheetTitle>
        <SheetDescription className="sr-only">{description}</SheetDescription>
        {children}
      </SheetContent>
    </Sheet>
  )
}
