/** Background-job bar shown under the stepper (design.md section 5, item 8). */
export function JobProgress({ message, progress }: { message: string; progress: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(progress)))
  return (
    <div className="mb-5" role="status" aria-live="polite">
      <div
        className="h-1.5 w-full rounded-full bg-stone-100"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className="h-1.5 rounded-full bg-[#0f766e] transition-[width] duration-150" style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-2 text-[12px] text-stone-600">{message}</p>
    </div>
  )
}
