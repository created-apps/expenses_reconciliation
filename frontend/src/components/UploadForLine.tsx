import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { cycleKeys } from '@/api/cycles'
import { entryAsInvoice, useInvoices, useReadNewInvoices } from '@/api/invoices'
import type { ResultInvoice } from '@/api/results'
import { useUploader } from '@/api/useUploader'
import { JobProgress } from '@/components/JobProgress'
import { UploadCard } from '@/components/UploadCard'
import { errorMessage } from '@/lib/api'
import { cn } from '@/lib/utils'

type Notice = { tone: 'ok' | 'warn' | 'error'; text: string }

/**
 * "Upload the invoice" in the drawer of a Review or Missing invoice line. The file is uploaded, only the new
 * file is read (every other invoice and match stays as it is), and what was read is handed back to be attached
 * to this line; the person checks the amount and saves, exactly as with an invoice found by search.
 */
export function UploadForLine({
  cycleId,
  isCredit,
  onFound,
}: {
  cycleId: string
  isCredit: boolean
  onFound: (invoices: ResultInvoice[]) => void
}) {
  const qc = useQueryClient()
  const uploader = useUploader({ slot: 'invoices', getCycleId: () => Promise.resolve(cycleId) })
  const read = useReadNewInvoices(cycleId)
  const [reading, setReading] = useState(false)
  const [notice, setNotice] = useState<Notice | null>(null)
  const handled = useRef(new Set<string>()) // uploaded files already sent to be read
  const waitingFor = useRef<string[]>([])
  // Polls the read job. Enabled only once the read has started, so an old "done" can't be mistaken for this one.
  const invoices = useInvoices(cycleId, read.isSuccess)
  const job = invoices.data?.job

  // 1. Files that finished uploading are read (only them).
  useEffect(() => {
    if (reading || uploader.uploading) return
    const fresh = uploader.rows.filter((r) => r.status === 'uploaded' && r.fileId && !handled.current.has(r.fileId))
    if (fresh.length === 0) return
    const ids = fresh.map((r) => r.fileId as string)
    ids.forEach((id) => handled.current.add(id))
    waitingFor.current = ids
    setNotice(null)
    setReading(true)
    read.reset()
    read.mutate(undefined, {
      onError: (error) => {
        setReading(false)
        setNotice({ tone: 'error', text: errorMessage(error, 'Couldn’t read the uploaded invoice. Please try again.') })
      },
    })
  }, [reading, uploader.uploading, uploader.rows])

  // 2. When the job has finished, hand what was read for these files to the line.
  useEffect(() => {
    if (!reading || !read.isSuccess || !invoices.data || job?.status === 'running') return
    setReading(false)
    void qc.invalidateQueries({ queryKey: cycleKeys.unused(cycleId) })
    if (job?.status === 'failed') {
      setNotice({ tone: 'error', text: job.message || 'Couldn’t read the uploaded invoice. Please try again.' })
      return
    }
    const ids = new Set(waitingFor.current)
    const entries = invoices.data.entries.filter((e) => ids.has(e.fileId))
    const found = entries
      .map(entryAsInvoice)
      .filter((i): i is NonNullable<typeof i> => i !== null)
      .filter((i) => isCredit || !i.isCreditNote)
    if (found.length > 0) {
      onFound(found)
      const checks = found.filter((i) => i.needsCheck).length
      setNotice({
        tone: checks > 0 ? 'warn' : 'ok',
        text:
          `Read ${found.length === 1 ? 'the invoice' : `${found.length} invoices`} and attached ${found.length === 1 ? 'it' : 'them'} below. ` +
          (checks > 0 ? 'Some details could not be read with certainty: check the amount, then ' : 'Check the amount, then ') +
          'Save.',
      })
    } else {
      const waiting = entries.some((e) => e.state === 'pending')
      setNotice({
        tone: 'warn',
        text: waiting
          ? 'Uploaded, but the invoice is waiting for the AI to read it. Check it on the Invoices step.'
          : 'Uploaded, but no invoice could be read from the file. Check it on the Invoices step.',
      })
    }
  }, [reading, read.isSuccess, invoices.data, job?.status])

  return (
    <div className="mt-3">
      {reading && <JobProgress message={job?.message || 'Reading the invoice…'} progress={job?.progress ?? 5} />}
      <UploadCard
        title="Upload the invoice"
        hint="PDF, PNG, JPG or ZIP"
        helper="It is read and attached to this charge. Nothing else in the reconciliation changes."
        accept=".pdf,.png,.jpg,.jpeg,.zip"
        multiple
        rows={uploader.rows}
        onAdd={uploader.addFiles}
        onDismiss={uploader.dismiss}
      />
      {notice && (
        <p
          role={notice.tone === 'error' ? 'alert' : 'status'}
          className={cn(
            'mt-2 text-[12px]',
            notice.tone === 'ok' && 'text-emerald-700',
            notice.tone === 'warn' && 'text-amber-700',
            notice.tone === 'error' && 'text-red-700',
          )}
        >
          {notice.text}
        </p>
      )}
    </div>
  )
}
