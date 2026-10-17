import { FileText, Menu } from 'lucide-react'
import { useState } from 'react'
import { Link, Outlet } from 'react-router-dom'

import { useAuth } from '@/auth/context'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'

function NavContent({ onNavigate }: { onNavigate?: () => void }) {
  const { email, signOut } = useAuth()
  return (
    <>
      <div className="px-2 text-[15px] font-semibold tracking-tight text-stone-900">Reconcile</div>
      <Link
        to="/"
        onClick={onNavigate}
        aria-current="page"
        className="mt-8 flex items-center gap-2 rounded-md bg-teal-50 px-2.5 py-2 text-[13px] font-medium text-teal-800 outline-none focus-visible:ring-2 focus-visible:ring-teal-600/40"
      >
        <FileText className="size-4" />
        Reconciliations
      </Link>
      <div className="mt-auto border-t border-stone-100 pt-4">
        <div className="truncate px-2 text-[12px] text-stone-500" title={email ?? undefined}>
          {email}
        </div>
        <button
          type="button"
          onClick={() => void signOut()}
          className="mt-2 rounded px-2 text-[12px] text-stone-500 outline-none hover:text-stone-900 focus-visible:ring-2 focus-visible:ring-teal-600/40"
        >
          Sign out
        </button>
      </div>
    </>
  )
}

/** Sidebar from `md` up; below `md` a top bar whose menu button opens the same nav as a sheet. */
export default function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false)
  return (
    <div className="flex min-h-screen bg-[#fafaf9] text-stone-900">
      <aside className="sticky top-0 hidden h-screen w-[220px] shrink-0 flex-col border-r border-stone-200 bg-white px-4 py-5 md:flex">
        <NavContent />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 items-center justify-between border-b border-stone-200 bg-white px-4 md:hidden">
          <span className="text-[15px] font-semibold tracking-tight">Reconcile</span>
          <button
            type="button"
            aria-label="Open menu"
            onClick={() => setMenuOpen(true)}
            className="rounded p-1.5 text-stone-600 outline-none hover:bg-stone-100 focus-visible:ring-2 focus-visible:ring-teal-600/40"
          >
            <Menu className="size-5" />
          </button>
        </header>

        <main className="min-w-0 flex-1 px-5 py-6 md:px-10 md:py-8">
          <div className="mx-auto max-w-[1240px]">
            <Outlet />
          </div>
        </main>
      </div>

      <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
        <SheetContent side="left" className="w-[240px] gap-0 bg-white px-4 py-5 data-[side=left]:w-[240px]">
          <SheetTitle className="sr-only">Menu</SheetTitle>
          <SheetDescription className="sr-only">Navigation</SheetDescription>
          <NavContent onNavigate={() => setMenuOpen(false)} />
        </SheetContent>
      </Sheet>
    </div>
  )
}
