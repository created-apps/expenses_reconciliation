import { useUploader } from '@/api/useUploader'
import { DetailSheet } from '@/components/DetailSheet'
import { UploadCard } from '@/components/UploadCard'
import { Button } from '@/components/ui/button'

/** "Add files" on the Invoices step: the same upload cards as New reconciliation, in a sheet. */
export function AddFilesSheet({
  cycleId,
  open,
  onOpenChange,
  onDone,
}: {
  cycleId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Called with the number of files that were stored. */
  onDone: (count: number) => void
}) {
  return (
    <DetailSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Add files"
      description="Add more invoices or an Amazon Business report to this reconciliation"
    >
      {/* Mounted only while open, so each opening starts with empty lists. */}
      {open && <AddFilesBody cycleId={cycleId} onDone={onDone} />}
    </DetailSheet>
  )
}

function AddFilesBody({ cycleId, onDone }: { cycleId: string; onDone: (count: number) => void }) {
  const getCycleId = () => Promise.resolve(cycleId)
  const invoices = useUploader({ slot: 'invoices', getCycleId })
  const amazon = useUploader({ slot: 'amazon_report', getCycleId })
  const count = invoices.uploadedCount + amazon.uploadedCount

  return (
    <div className="mt-4 flex flex-col gap-3">
      <UploadCard
        title="Invoices"
        hint="PDF, PNG, JPG or ZIP"
        helper="Add invoices that were missing from the first upload."
        accept=".pdf,.png,.jpg,.jpeg,.zip"
        multiple
        rows={invoices.rows}
        onAdd={invoices.addFiles}
        onDismiss={invoices.dismiss}
      />
      <UploadCard
        title="Amazon Business report"
        hint="Optional · one CSV"
        helper="Business Analytics → Reconciliation report → Download CSV. A new report replaces the old one."
        accept=".csv,text/csv"
        rows={amazon.rows}
        onAdd={amazon.addFiles}
        onDismiss={amazon.dismiss}
      />
      <div className="flex justify-end">
        <Button disabled={invoices.uploading || amazon.uploading} onClick={() => onDone(count)}>
          Done
        </Button>
      </div>
    </div>
  )
}
