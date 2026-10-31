import { ExternalLink } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { openStoredFile } from '@/api/cycles'
import {
  useAddVendor,
  useCorrectInvoice,
  useNotAnInvoice,
  useRestoreFile,
  type InvoiceChanges,
  type InvoiceEntry,
} from '@/api/invoices'
import { DetailSheet } from '@/components/DetailSheet'
import { ExtractionBadge } from '@/components/StatusBadge'
import { Banner } from '@/components/Banner'
import { Button } from '@/components/ui/button'
import { decimalToMinor, minorToDecimal } from '@/lib/format'
import { errorMessage } from '@/lib/api'
import { SOURCE_LABEL } from '@/lib/invoiceLabels'

const ADD_VENDOR = '__add_vendor__' // the select's "+ Add a vendor…" row, never a real vendor key

const inputClass =
  'mt-1 h-8 w-full rounded border border-stone-200 bg-white px-2 text-[12px] outline-none focus:border-teal-600 focus:ring-2 focus:ring-teal-100 disabled:bg-stone-50 disabled:text-stone-500'

/** What to tell the person about a file that has no invoice row to edit. */
function fileOnlyNote(entry: InvoiceEntry): string {
  switch (entry.state) {
    case 'duplicate':
      return entry.duplicateOfName
        ? `Same invoice as ${entry.duplicateOfName} (same vendor, number and total). It is not used twice.`
        : 'This file has exactly the same content as another uploaded file, so it is not read again.'
    case 'ignored':
      return entry.fileNote ?? 'This file is set aside and is not used.'
    case 'failed':
      return entry.fileNote ?? 'This file could not be stored. Add it again.'
    default:
      return 'This file has not been read yet. Use Read invoices.'
  }
}

export function InvoiceSheet({
  entry,
  vendors,
  cycleId,
  onClose,
}: {
  entry: InvoiceEntry | null
  vendors: { key: string; name: string }[]
  cycleId: string
  onClose: () => void
}) {
  return (
    <DetailSheet
      open={entry !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
      title="Invoice details"
      description="Extracted invoice fields. Correct any value and save."
    >
      {entry && <Body key={entry.key} entry={entry} vendors={vendors} cycleId={cycleId} onClose={onClose} />}
    </DetailSheet>
  )
}

function Body({
  entry,
  vendors,
  cycleId,
  onClose,
}: {
  entry: InvoiceEntry
  vendors: { key: string; name: string }[]
  cycleId: string
  onClose: () => void
}) {
  const correct = useCorrectInvoice(cycleId)
  const addVendor = useAddVendor(cycleId)
  // A vendor typed in by hand, shown in the list straight away (the list reloads from the server as well).
  const [extraVendors, setExtraVendors] = useState<{ key: string; name: string }[]>([])
  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const [newStatement, setNewStatement] = useState('')
  const notInvoice = useNotAnInvoice(cycleId)
  const restoreFile = useRestoreFile(cycleId)
  const [vendorKey, setVendorKey] = useState(entry.vendorKey ?? '')
  const [invoiceNo, setInvoiceNo] = useState(entry.invoiceNo ?? '')
  const [orderId, setOrderId] = useState(entry.orderId ?? '')
  const [invoiceDate, setInvoiceDate] = useState(entry.invoiceDate ?? '')
  const [orderDate, setOrderDate] = useState(entry.orderDate ?? '')
  const [currency, setCurrency] = useState<'INR' | 'USD'>(entry.currency ?? 'INR')
  const [total, setTotal] = useState(entry.totalMinor === null ? '' : minorToDecimal(entry.totalMinor))

  const editable = entry.invoiceId !== null
  const totalMinor = total.trim() === '' ? null : decimalToMinor(total)
  const totalInvalid = total.trim() !== '' && totalMinor === null

  const changes: InvoiceChanges = {}
  if ((vendorKey || null) !== entry.vendorKey) changes.vendorKey = vendorKey || null
  if ((invoiceNo.trim() || null) !== entry.invoiceNo) changes.invoiceNo = invoiceNo.trim() || null
  if ((orderId.trim() || null) !== entry.orderId) changes.orderId = orderId.trim() || null
  if ((invoiceDate || null) !== entry.invoiceDate) changes.invoiceDate = invoiceDate || null
  if ((orderDate || null) !== entry.orderDate) changes.orderDate = orderDate || null
  if (currency !== (entry.currency ?? 'INR')) changes.currency = currency
  if (!totalInvalid && totalMinor !== entry.totalMinor) changes.totalMinor = totalMinor
  const dirty = Object.keys(changes).length > 0

  function save() {
    if (!entry.invoiceId) return
    correct.mutate(
      { invoiceId: entry.invoiceId, changes },
      {
        onSuccess: () => {
          toast('Saved')
          onClose()
        },
        onError: (error) => toast.error(errorMessage(error, 'Couldn’t save the invoice.')),
      },
    )
  }

  const vendorOptions = [...vendors, ...extraVendors.filter((x) => !vendors.some((v) => v.key === x.key))]

  function addNewVendor() {
    addVendor.mutate(
      { name: newName, statementText: newStatement },
      {
        onSuccess: (vendor) => {
          setExtraVendors((prev) => [...prev, vendor])
          setVendorKey(vendor.key) // chosen for this invoice; it is saved with the other changes
          setAdding(false)
          setNewName('')
          setNewStatement('')
          toast(`${vendor.name} added to the vendor list`)
        },
        onError: (error) => toast.error(errorMessage(error, 'Couldn’t add the vendor.')),
      },
    )
  }

  function setAside() {
    if (!entry.invoiceId) return
    notInvoice.mutate(entry.invoiceId, {
      onSuccess: () => {
        toast('Marked as not an invoice')
        onClose()
      },
      onError: (error) => toast.error(errorMessage(error, 'Couldn’t update the file.')),
    })
  }

  function restore() {
    restoreFile.mutate(entry.fileId, {
      onSuccess: () => {
        toast('File restored. Click Read invoices to read it again.')
        onClose()
      },
      onError: (error) => toast.error(errorMessage(error, 'Couldn’t restore the file.')),
    })
  }

  return (
    <div>
      <div className="mt-1 flex items-center gap-2 text-[12px] text-stone-500">
        <span className="truncate" title={entry.fileName}>
          {entry.fileName}
        </span>
        <ExtractionBadge state={entry.state} />
      </div>
      {entry.hasCopy && (
        <Button variant="secondary" className="mt-3" onClick={() => void openStoredFile(entry.fileId)}>
          <ExternalLink />
          Open file
        </Button>
      )}

      {entry.invoiceId === null ? (
        <>
          <p className="mt-5 text-[12px] text-stone-600">{fileOnlyNote(entry)}</p>
          {entry.canRestore && (
            <div className="mt-4">
              <p className="mb-2 text-[12px] text-stone-600">
                Set aside by mistake? Restore it, then click Read invoices to read it again.
              </p>
              <Button variant="secondary" onClick={restore} disabled={restoreFile.isPending}>
                {restoreFile.isPending ? 'Restoring…' : 'Restore this file'}
              </Button>
            </div>
          )}
        </>
      ) : (
        <>
          {entry.problems.length > 0 && entry.state !== 'pending' && (
            <Banner tone="warning" className="mt-4">
              <p className="font-medium">Needs a check</p>
              <ul className="mt-1 list-disc pl-4">
                {entry.problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </Banner>
          )}
          {entry.state === 'pending' && (
            <p className="mt-4 text-[12px] text-stone-600">
              Not read yet{entry.problems[0] ? `: ${entry.problems[0]}` : ''}. Use Read invoices once that is fixed, or type
              the values in now.
            </p>
          )}
          {entry.duplicateOfName && (
            <p className="mt-4 text-[12px] text-stone-600">
              Same vendor, number and total as {entry.duplicateOfName}; it is not used twice.
            </p>
          )}

          <div className="mt-5 grid grid-cols-2 gap-3">
            <label className="text-[11px] font-medium text-stone-600">
              Vendor
              <select
                className={inputClass}
                value={vendorKey}
                disabled={!editable}
                onChange={(e) => {
                  if (e.target.value === ADD_VENDOR) setAdding(true)
                  else setVendorKey(e.target.value)
                }}
              >
                <option value="">Not recognised</option>
                {vendorOptions.map((v) => (
                  <option key={v.key} value={v.key}>
                    {v.name}
                  </option>
                ))}
                <option value={ADD_VENDOR}>+ Add a vendor…</option>
              </select>
            </label>
            {adding && (
              <div className="col-span-2 rounded-md border border-stone-200 bg-stone-50 p-3">
                <p className="text-[12px] font-medium text-stone-800">Add a vendor to the list</p>
                <label className="mt-2 block text-[11px] font-medium text-stone-600">
                  Vendor name
                  <input
                    className={inputClass}
                    value={newName}
                    maxLength={60}
                    autoFocus
                    placeholder="For example: Zoom"
                    onChange={(e) => setNewName(e.target.value)}
                  />
                </label>
                <label className="mt-2 block text-[11px] font-medium text-stone-600">
                  As it appears on the card statement <span className="font-normal text-stone-400">(optional)</span>
                  <input
                    className={inputClass}
                    value={newStatement}
                    maxLength={60}
                    placeholder="Leave empty if it is the same as the name"
                    onChange={(e) => setNewStatement(e.target.value)}
                  />
                </label>
                <p className="mt-2 text-[11px] text-stone-500">
                  The vendor stays in the list for every reconciliation. Run matching again so statement lines with this
                  name pick up its invoices.
                </p>
                <div className="mt-3 flex justify-end gap-2">
                  <Button variant="secondary" onClick={() => setAdding(false)} disabled={addVendor.isPending}>
                    Cancel
                  </Button>
                  <Button onClick={addNewVendor} disabled={addVendor.isPending || newName.trim().length < 2}>
                    {addVendor.isPending ? 'Adding…' : 'Add vendor'}
                  </Button>
                </div>
              </div>
            )}
            <label className="text-[11px] font-medium text-stone-600">
              Invoice no.
              <input className={inputClass} value={invoiceNo} disabled={!editable} onChange={(e) => setInvoiceNo(e.target.value)} />
            </label>
            <label className="text-[11px] font-medium text-stone-600">
              Order ID
              <input className={inputClass} value={orderId} disabled={!editable} onChange={(e) => setOrderId(e.target.value)} />
            </label>
            <label className="text-[11px] font-medium text-stone-600">
              Invoice date
              <input type="date" className={inputClass} value={invoiceDate} disabled={!editable} onChange={(e) => setInvoiceDate(e.target.value)} />
            </label>
            <label className="text-[11px] font-medium text-stone-600">
              Order date
              <input type="date" className={inputClass} value={orderDate} disabled={!editable} onChange={(e) => setOrderDate(e.target.value)} />
            </label>
            <label className="text-[11px] font-medium text-stone-600">
              Currency
              <select
                className={inputClass}
                value={currency}
                disabled={!editable}
                onChange={(e) => setCurrency(e.target.value as 'INR' | 'USD')}
              >
                <option value="INR">INR (₹)</option>
                <option value="USD">USD ($)</option>
              </select>
            </label>
            <label className="text-[11px] font-medium text-stone-600">
              Total
              <input
                className={inputClass}
                inputMode="decimal"
                value={total}
                disabled={!editable}
                aria-invalid={totalInvalid}
                onChange={(e) => setTotal(e.target.value)}
              />
              {totalInvalid && <span className="mt-1 block text-[11px] font-normal text-red-700">Enter a number such as 928.27</span>}
            </label>
          </div>
          <p className="mt-3 text-[11px] text-stone-400">
            Source: {entry.source ? SOURCE_LABEL[entry.source] : 'Not read yet'}
            {entry.isCreditNote && ' · credit note'}
          </p>
          {entry.source === 'vision' && (
            <p className="mt-1 text-[11px] text-stone-500">
              Read by AI from the image. Check the values against the file; correct anything that is wrong.
            </p>
          )}

          <div className="mt-5 flex justify-end gap-2">
            <Button variant="secondary" onClick={setAside} disabled={notInvoice.isPending || correct.isPending}>
              Not an invoice
            </Button>
            <Button onClick={save} disabled={!dirty || totalInvalid || correct.isPending || notInvoice.isPending}>
              Save
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
