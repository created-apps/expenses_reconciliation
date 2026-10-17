import { UploadCloud } from 'lucide-react'
import { useId, useRef, useState } from 'react'

import type { UploadRow } from '@/api/useUploader'
import { FileRow } from '@/components/FileRow'
import { cn } from '@/lib/utils'

export function UploadCard({
  title,
  hint,
  helper,
  accept,
  multiple = false,
  rows,
  onAdd,
  onDismiss,
}: {
  title: string
  hint: string
  helper: string
  accept: string
  multiple?: boolean
  rows: UploadRow[]
  onAdd: (files: File[]) => void
  onDismiss?: (key: string) => void
}) {
  const inputId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  return (
    <section className="rounded-md border border-stone-200 bg-white p-5">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-[14px] font-semibold text-stone-900">
            {title} <span className="ml-1 text-[11px] font-normal text-stone-500">{hint}</span>
          </h2>
          <p className="mt-1 text-[12px] text-stone-500">{helper}</p>
        </div>
        <UploadCloud className="size-5 text-stone-400" />
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          onAdd(Array.from(e.dataTransfer.files))
        }}
        className={cn(
          'mt-4 flex min-h-[76px] items-center justify-center rounded-md border border-dashed text-[13px] text-stone-500',
          dragging ? 'border-teal-600 bg-teal-50/50' : 'border-stone-300 bg-stone-50/50',
        )}
      >
        Drop files here or
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="ml-1 rounded font-medium text-teal-700 outline-none focus-visible:ring-2 focus-visible:ring-teal-600/40"
        >
          browse
        </button>
        <label htmlFor={inputId} className="sr-only">
          {title}
        </label>
        <input
          id={inputId}
          ref={inputRef}
          type="file"
          accept={accept}
          multiple={multiple}
          className="sr-only"
          onChange={(e) => {
            onAdd(Array.from(e.target.files ?? []))
            e.target.value = ''
          }}
        />
      </div>

      {rows.length > 0 && (
        <div className="mt-3 flex max-h-80 flex-col gap-2 overflow-y-auto pr-1" aria-live="polite">
          {rows.map((row) => (
            <FileRow key={row.key} row={row} onDismiss={onDismiss} />
          ))}
        </div>
      )}
    </section>
  )
}
