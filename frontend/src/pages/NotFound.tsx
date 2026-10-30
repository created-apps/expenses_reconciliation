import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <main className="mx-auto max-w-[760px] p-8">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <Link to="/" className="mt-4 inline-block text-sm text-teal-700 underline">
        Back to reconciliations
      </Link>
    </main>
  )
}
