import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useRef, useState } from 'react'
import { toast } from 'sonner'

import { cycleKeys, uploadFiles, type StoredFile, type UploadSlot } from '@/api/cycles'
import { errorMessage } from '@/lib/api'

export type UploadRowStatus =
  | 'uploading'
  | 'uploaded'
  | 'duplicate'
  | 'unsupported'
  | 'failed'
  | 'ignored'
  | 'expanded'

/** One line in an upload card. */
export type UploadRow = {
  key: string
  name: string
  size: number | null
  status: UploadRowStatus
  note?: string | null
  /** Set for files that are stored and can be opened. */
  fileId?: string
  /** True for files that came out of a ZIP. */
  indent?: boolean
}

/** A stored file as an upload-card row (used for files that were uploaded earlier, too). */
export function storedFileRow(file: StoredFile, all: StoredFile[] = []): UploadRow {
  const base = { key: file.id, name: file.name, size: file.size, indent: file.parentId !== null }
  const fileId = file.hasCopy ? file.id : undefined
  if (file.status === 'failed') return { ...base, status: 'failed', note: file.error, fileId }
  if (file.kind === 'ignored') return { ...base, status: 'ignored', note: file.note, fileId }
  if (file.status === 'duplicate') return { ...base, status: 'duplicate', note: file.note, fileId }
  if (file.kind === 'zip') {
    const members = all.filter((f) => f.parentId === file.id).length
    return { ...base, status: 'expanded', note: `${members} ${members === 1 ? 'file' : 'files'}`, fileId }
  }
  return { ...base, status: 'uploaded', fileId }
}

let pendingCounter = 0

/**
 * State and actions for one upload card. Files are sent to the API as soon as they are chosen;
 * the card shows what the server decided for each one (stored, duplicate, ignored, rejected...).
 */
export function useUploader({ slot, getCycleId }: { slot: UploadSlot; getCycleId: () => Promise<string> }) {
  const queryClient = useQueryClient()
  const [rows, setRows] = useState<UploadRow[]>([])
  const [busy, setBusy] = useState(0)
  const getCycleIdRef = useRef(getCycleId)
  getCycleIdRef.current = getCycleId
  const single = slot !== 'invoices'

  const addFiles = useCallback(
    async (files: File[]) => {
      if (files.length === 0) return
      const keys = files.map(() => `pending-${pendingCounter++}`)
      const pending: UploadRow[] = files.map((f, i) => ({ key: keys[i], name: f.name, size: f.size, status: 'uploading' }))
      setRows((prev) => [...(single ? [] : prev), ...pending])
      setBusy((n) => n + 1)
      try {
        const cycleId = await getCycleIdRef.current()
        const result = await uploadFiles(cycleId, slot, files)
        const stored = result.files.map((f) => storedFileRow(f, result.files))
        const rejected: UploadRow[] = result.rejected.map((r, i) => ({
          key: `rejected-${pendingCounter++}-${i}`,
          name: r.name,
          size: null,
          status: 'unsupported',
          note: r.message,
        }))
        setRows((prev) => [...prev.filter((r) => !keys.includes(r.key)), ...stored, ...rejected])
        void queryClient.invalidateQueries({ queryKey: cycleKeys.all })
        void queryClient.invalidateQueries({ queryKey: cycleKeys.one(cycleId) })
        void queryClient.invalidateQueries({ queryKey: cycleKeys.files(cycleId) })
        // A replaced statement starts again from nothing.
        if (slot === 'statement') void queryClient.invalidateQueries({ queryKey: cycleKeys.statement(cycleId) })
        if (slot === 'invoices') void queryClient.invalidateQueries({ queryKey: cycleKeys.invoices(cycleId) })
        if (slot === 'amazon_report') void queryClient.invalidateQueries({ queryKey: cycleKeys.amazon(cycleId) })
      } catch (error) {
        const message = errorMessage(error, 'Upload failed. Please try again.')
        setRows((prev) => prev.map((r) => (keys.includes(r.key) ? { ...r, status: 'failed', note: message } : r)))
        toast.error(message)
      } finally {
        setBusy((n) => n - 1)
      }
    },
    [queryClient, single, slot],
  )

  /** Dismiss a row that never reached storage (rejected or failed). Stored files stay. */
  const dismiss = useCallback((key: string) => setRows((prev) => prev.filter((r) => r.key !== key)), [])

  return {
    rows,
    addFiles,
    dismiss,
    uploading: busy > 0,
    uploadedCount: rows.filter((r) => r.status === 'uploaded').length,
  }
}
