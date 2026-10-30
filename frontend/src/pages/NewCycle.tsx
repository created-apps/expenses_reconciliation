import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { useCreateCycle, useDeleteCycle } from '@/api/cycles'
import { useUploader } from '@/api/useUploader'
import { PageHeader } from '@/components/PageHeader'
import { UploadCard } from '@/components/UploadCard'
import { Button } from '@/components/ui/button'
import { errorMessage } from '@/lib/api'

export default function NewCycle() {
  const navigate = useNavigate()
  const createCycle = useCreateCycle()
  const deleteCycle = useDeleteCycle()
  const [leaving, setLeaving] = useState(false)

  // The reconciliation is created (as a draft) when the first file is added, then reused by all three cards.
  const cycleIdPromise = useRef<Promise<string> | null>(null)
  const createRef = useRef(createCycle.mutateAsync)
  createRef.current = createCycle.mutateAsync
  const ensureCycle = () => {
    if (!cycleIdPromise.current) {
      cycleIdPromise.current = createRef.current().then(
        (cycle) => cycle.id,
        (error: unknown) => {
          cycleIdPromise.current = null
          throw error
        },
      )
    }
    return cycleIdPromise.current
  }

  const statement = useUploader({ slot: 'statement', getCycleId: ensureCycle })
  const invoices = useUploader({ slot: 'invoices', getCycleId: ensureCycle })
  const amazon = useUploader({ slot: 'amazon_report', getCycleId: ensureCycle })

  const uploading = statement.uploading || invoices.uploading || amazon.uploading
  // Continue needs a statement and at least one invoice that was stored (duplicates and ignored copies don't count).
  const ready = statement.uploadedCount === 1 && invoices.uploadedCount >= 1 && !uploading

  async function cancel() {
    setLeaving(true)
    try {
      // Discard the draft that this screen created, together with whatever was uploaded to it.
      if (cycleIdPromise.current) await deleteCycle.mutateAsync(await cycleIdPromise.current)
      navigate('/')
    } catch (error) {
      toast.error(errorMessage(error, 'Could not discard the draft.'))
      setLeaving(false)
    }
  }

  async function next() {
    if (!cycleIdPromise.current) return
    navigate(`/cycles/${await cycleIdPromise.current}/statement`)
  }

  return (
    <>
      <PageHeader title="New reconciliation" description="Add the files for one card statement period." />
      <div className="mt-6 flex max-w-[760px] flex-col gap-3">
        <UploadCard
          title="Card statement"
          hint="Required · one PDF"
          helper="Download the PDF from ICICI net banking. Photos aren’t supported."
          accept=".pdf,application/pdf"
          rows={statement.rows}
          onAdd={statement.addFiles}
          onDismiss={statement.dismiss}
        />
        <UploadCard
          title="Invoices"
          hint="Required · PDF, PNG, JPG or ZIP"
          helper="Add all invoices received during this statement period."
          accept=".pdf,.png,.jpg,.jpeg,.zip"
          multiple
          rows={invoices.rows}
          onAdd={invoices.addFiles}
          onDismiss={invoices.dismiss}
        />
        <UploadCard
          title="Amazon Business report"
          hint="Optional · one CSV"
          helper="Business Analytics → Reconciliation report → Download CSV. Makes Amazon matching exact."
          accept=".csv,text/csv"
          rows={amazon.rows}
          onAdd={amazon.addFiles}
          onDismiss={amazon.dismiss}
        />
      </div>
      <div className="mt-6 flex max-w-[760px] items-center justify-end gap-2 border-t border-stone-200 pt-4">
        {!ready && (
          <span className="mr-auto text-[12px] text-stone-500">
            {uploading ? 'Uploading…' : 'Add the statement and at least one invoice to continue.'}
          </span>
        )}
        <Button variant="secondary" onClick={() => void cancel()} disabled={leaving}>
          Cancel
        </Button>
        <Button disabled={!ready || leaving} onClick={() => void next()}>
          Continue
        </Button>
      </div>
    </>
  )
}
