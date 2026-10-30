import { Check, FileText, Loader2, X } from 'lucide-react'

import type { UploadRow, UploadRowStatus } from '@/api/useUploader'
import { openStoredFile } from '@/api/cycles'
import { formatSize } from '@/lib/format'
import { cn } from '@/lib/utils'

const STATUS: Record<UploadRowStatus, { label: string; style: string }> = {
  uploading: { label: 'Uploading', style: 'text-stone-500' },
  uploaded: { label: 'Uploaded', style: 'text-emerald-700' },
  duplicate: { label: 'Duplicate', style: 'text-amber-700' },
  unsupported: { label: 'Not supported', style: 'text-red-700' },
  failed: { label: 'Failed', style: 'text-red-700' },
  ignored: { label: 'Ignored', style: 'text-stone-600' },
  expanded: { label: 'Expanded', style: 'text-stone-600' },
}

/** Label for a row's status, with the reason where there is one ("Ignored – copy of the statement"). */
export function statusLabel(row: Pick<UploadRow, 'status' | 'note'>): string {
  const { label } = STATUS[row.status]
  if (!row.note) return label
  if (row.status === 'ignored') return `${label} – ${row.note}`
  if (row.status === 'expanded') return `${label} · ${row.note}`
  return label
}

export function FileRow({ row, onDismiss }: { row: UploadRow; onDismiss?: (key: string) => void }) {
  const status = STATUS[row.status]
  const detail = row.status === 'failed' || row.status === 'unsupported' || row.status === 'duplicate' ? row.note : null
  // Only rows that never reached storage can be dismissed; stored files stay with the reconciliation.
  const canDismiss = onDismiss !== undefined && row.fileId === undefined && row.status !== 'uploading'

  return (
    <div className={cn('flex items-center justify-between gap-3 rounded border border-stone-100 px-3 py-2 text-[12px]', row.indent && 'ml-5')}>
      <span className="flex min-w-0 items-center gap-2 text-stone-700">
        <FileText className="size-4 shrink-0 text-stone-400" />
        {row.fileId ? (
          <button
            type="button"
            onClick={() => void openStoredFile(row.fileId!)}
            title={`Open ${row.name}`}
            className="truncate rounded text-left outline-none hover:text-teal-800 hover:underline focus-visible:ring-2 focus-visible:ring-teal-600/40"
          >
            {row.name}
          </button>
        ) : (
          <span className="truncate" title={row.name}>
            {row.name}
          </span>
        )}
      </span>
      <span className="flex shrink-0 items-center gap-3 text-stone-400">
        <span className={cn('flex items-center gap-1', status.style)} title={detail ?? undefined}>
          {row.status === 'uploading' && <Loader2 className="size-3 animate-spin" />}
          {row.status === 'uploaded' && <Check className="size-3" />}
          {statusLabel(row)}
        </span>
        {detail && <span className="hidden max-w-[220px] truncate text-stone-500 sm:inline">{detail}</span>}
        {row.size !== null && <span className="tabular-nums">{formatSize(row.size)}</span>}
        {canDismiss && (
          <button
            type="button"
            aria-label={`Dismiss ${row.name}`}
            onClick={() => onDismiss(row.key)}
            className="rounded p-0.5 text-stone-400 outline-none hover:text-stone-700 focus-visible:ring-2 focus-visible:ring-teal-600/40"
          >
            <X className="size-4" />
          </button>
        )}
      </span>
    </div>
  )
}
