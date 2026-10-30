import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

// Variants follow design.md section 2:
//   default   = Primary button (teal)
//   secondary = Secondary button (white, stone border); `outline` is an alias
//   destructive = delete confirmations (red-700)
const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center gap-2 rounded-md border border-transparent bg-clip-padding text-[13px] font-medium whitespace-nowrap transition-all outline-none select-none focus-visible:ring-2 focus-visible:ring-teal-600/40 active:not-aria-[haspopup]:translate-y-px disabled:pointer-events-none disabled:opacity-40 aria-invalid:border-destructive [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-[#0f766e] text-white shadow-sm hover:bg-[#0d625c]",
        secondary:
          "border-stone-200 bg-white text-stone-700 hover:bg-stone-50 aria-expanded:bg-stone-50",
        outline:
          "border-stone-200 bg-white text-stone-700 hover:bg-stone-50 aria-expanded:bg-stone-50",
        ghost: "text-stone-600 hover:bg-stone-100 hover:text-stone-900",
        destructive: "bg-red-700 text-white shadow-sm hover:bg-red-800",
        link: "text-teal-700 underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-3.5",
        xs: "h-6 gap-1 px-2 text-xs [&_svg:not([class*='size-'])]:size-3",
        sm: "h-8 px-3 text-[12px] [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-9 px-3.5",
        icon: "size-8",
        "icon-xs": "size-6 [&_svg:not([class*='size-'])]:size-3",
        "icon-sm": "size-7",
        "icon-lg": "size-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
