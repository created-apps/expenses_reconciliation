import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { apiFetch, errorMessage } from '@/lib/api'
import type { Cycle, CycleStatus } from '@/types'

// ---- Shapes as the API sends them (snake_case) --------------------------------------------------

type CycleDto = {
  id: string
  label: string | null
  status: CycleStatus
  period_start: string | null
  period_end: string | null
  matched_lines: number | null
  total_lines: number | null
  open_items: number | null
  created_at: string
  updated_at: string
  last_exported_at?: string | null
  edited_since_export?: boolean
  files?: {
    statement: number
    invoices: number
    ignored: number
    duplicates: number
    amazon_reports: number
    zips: number
    total: number
  }
}

type FileDto = {
  id: string
  kind: 'statement' | 'invoice' | 'amazon_report' | 'zip' | 'ignored'
  original_name: string
  size_bytes: number | null
  mime_type: string | null
  parent_file_id: string | null
  status: 'uploaded' | 'processed' | 'failed' | 'duplicate'
  note: string | null
  error: string | null
  has_copy: boolean
  created_at: string
}

type UploadDto = { files: FileDto[]; rejected: { name: string; message: string }[] }

// ---- App shapes ---------------------------------------------------------------------------------

export type FileCounts = {
  statement: number
  invoices: number
  ignored: number
  duplicates: number
  amazonReports: number
  zips: number
  total: number
}

/** `editedSinceExport`: exported before and edited since, so the Excel on disk is out of date. */
export type CycleDetail = Cycle & { fileCounts: FileCounts; lastExportedAt: string | null; editedSinceExport: boolean }

export type StoredFile = {
  id: string
  kind: FileDto['kind']
  name: string
  size: number | null
  mimeType: string | null
  parentId: string | null
  status: FileDto['status']
  note: string | null
  error: string | null
  hasCopy: boolean
}

export type UploadSlot = 'statement' | 'invoices' | 'amazon_report'
export type UploadResult = { files: StoredFile[]; rejected: { name: string; message: string }[] }

function toCycle(d: CycleDto): Cycle {
  return {
    id: d.id,
    label: d.label,
    periodStart: d.period_start,
    periodEnd: d.period_end,
    status: d.status,
    matchedLines: d.matched_lines,
    totalLines: d.total_lines,
    openItems: d.open_items,
    createdAt: d.created_at,
    updatedAt: d.updated_at,
  }
}

function toCycleDetail(d: CycleDto): CycleDetail {
  const f = d.files
  return {
    ...toCycle(d),
    lastExportedAt: d.last_exported_at ?? null,
    editedSinceExport: d.edited_since_export ?? false,
    fileCounts: {
      statement: f?.statement ?? 0,
      invoices: f?.invoices ?? 0,
      ignored: f?.ignored ?? 0,
      duplicates: f?.duplicates ?? 0,
      amazonReports: f?.amazon_reports ?? 0,
      zips: f?.zips ?? 0,
      total: f?.total ?? 0,
    },
  }
}

function toFile(d: FileDto): StoredFile {
  return {
    id: d.id,
    kind: d.kind,
    name: d.original_name,
    size: d.size_bytes,
    mimeType: d.mime_type,
    parentId: d.parent_file_id,
    status: d.status,
    note: d.note,
    error: d.error,
    hasCopy: d.has_copy,
  }
}

// ---- Queries and mutations ----------------------------------------------------------------------

export const cycleKeys = {
  all: ['cycles'] as const,
  one: (id: string) => ['cycle', id] as const,
  files: (id: string) => ['cycle', id, 'files'] as const,
  statement: (id: string) => ['cycle', id, 'statement'] as const,
  invoices: (id: string) => ['cycle', id, 'invoices'] as const,
  amazon: (id: string) => ['cycle', id, 'amazon-report'] as const,
  matching: (id: string) => ['cycle', id, 'matching'] as const,
  export: (id: string) => ['cycle', id, 'export'] as const,
  lines: (id: string) => ['cycle', id, 'lines'] as const,
  unused: (id: string) => ['cycle', id, 'unused'] as const,
  amazonFetch: (id: string) => ['cycle', id, 'amazon-to-fetch'] as const,
}

export function useCycles() {
  return useQuery({
    queryKey: cycleKeys.all,
    queryFn: async () => (await apiFetch<CycleDto[]>('/api/cycles')).map(toCycle),
  })
}

export function useCycle(id: string | undefined) {
  return useQuery({
    queryKey: cycleKeys.one(id ?? ''),
    queryFn: async () => toCycleDetail(await apiFetch<CycleDto>(`/api/cycles/${id}`)),
    enabled: Boolean(id),
  })
}

export function useCycleFiles(id: string | undefined) {
  return useQuery({
    queryKey: cycleKeys.files(id ?? ''),
    queryFn: async () => (await apiFetch<FileDto[]>(`/api/cycles/${id}/files`)).map(toFile),
    enabled: Boolean(id),
  })
}

export function useCreateCycle() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () =>
      toCycle(
        await apiFetch<CycleDto>('/api/cycles', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: cycleKeys.all }),
  })
}

export function useDeleteCycle() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/api/cycles/${id}`, { method: 'DELETE' }),
    onSuccess: (_data, id) => {
      qc.removeQueries({ queryKey: ['cycle', id] })
      return qc.invalidateQueries({ queryKey: cycleKeys.all })
    },
  })
}

export async function uploadFiles(cycleId: string, slot: UploadSlot, files: File[]): Promise<UploadResult> {
  const form = new FormData()
  form.append('kind', slot)
  for (const file of files) form.append('files', file, file.name)
  const dto = await apiFetch<UploadDto>(`/api/cycles/${cycleId}/files`, { method: 'POST', body: form })
  return { files: dto.files.map(toFile), rejected: dto.rejected }
}

/**
 * Opens a stored file in a new tab through a short-lived signed link.
 * The tab is opened first, inside the click, so the browser does not block it as a pop-up.
 */
export async function openStoredFile(fileId: string): Promise<void> {
  const tab = window.open('about:blank', '_blank')
  if (!tab) {
    toast.error('Your browser blocked the new tab. Allow pop-ups for this site and try again.')
    return
  }
  try {
    const { url } = await apiFetch<{ url: string }>(`/api/files/${fileId}/url`)
    tab.opener = null
    tab.location.href = url
  } catch (error) {
    tab.close()
    toast.error(errorMessage(error, 'Could not open the file.'))
  }
}
