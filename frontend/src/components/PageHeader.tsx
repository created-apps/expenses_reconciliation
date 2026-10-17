export function PageHeader({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: React.ReactNode
}) {
  return (
    <header className="flex items-start justify-between gap-4 border-b border-stone-200 pb-5">
      <div>
        <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-stone-900">{title}</h1>
        {description && <p className="mt-1 text-[13px] text-stone-500">{description}</p>}
      </div>
      {action}
    </header>
  )
}
