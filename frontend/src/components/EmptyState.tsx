export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex min-h-48 flex-col items-center justify-center rounded-md border border-dashed border-stone-300 bg-white px-4 text-center">
      <div className="text-[14px] font-semibold text-stone-900">{title}</div>
      {description && <p className="mt-1 text-[12px] text-stone-500">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
