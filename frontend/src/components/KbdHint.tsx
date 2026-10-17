export function Kbd({ children }: { children: React.ReactNode }) {
  return <kbd className="rounded border border-stone-200 bg-white px-1.5 py-0.5 font-mono">{children}</kbd>
}

/** Keyboard hints for the Results step: j / k move, Enter open, Esc close. */
export function KbdHint() {
  return (
    <div className="hidden items-center gap-1 text-[11px] text-stone-500 sm:flex">
      <Kbd>j</Kbd>
      <Kbd>k</Kbd> move
      <span className="ml-2">
        <Kbd>Enter</Kbd>
      </span>{' '}
      open
      <span className="ml-2">
        <Kbd>Esc</Kbd>
      </span>{' '}
      close
    </div>
  )
}
