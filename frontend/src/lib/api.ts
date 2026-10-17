import { supabase } from '@/lib/supabase'

// Local development falls back to the local API. A production build without VITE_API_BASE_URL must not quietly
// call localhost from a user's browser: it says what is missing instead.
const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.PROD ? '' : 'http://localhost:8000')).replace(/\/$/, '')
const NOT_CONFIGURED = 'The app is not configured: VITE_API_BASE_URL is missing from this build.'

/** status 0 means the server could not be reached at all. */
export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/**
 * Calls the backend with the current Supabase access token as a Bearer token.
 * JSON bodies: pass `body: JSON.stringify(...)` and a JSON content type. FormData: pass it as `body`
 * and leave the content type alone (the browser adds the multipart boundary).
 */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const session = supabase ? (await supabase.auth.getSession()).data.session : null
  const headers = new Headers(init.headers)
  if (session?.access_token) headers.set('Authorization', `Bearer ${session.access_token}`)

  if (!baseUrl) throw new ApiError(0, NOT_CONFIGURED)
  let response: Response
  try {
    response = await fetch(`${baseUrl}${path}`, { ...init, headers })
  } catch {
    throw new ApiError(0, 'Could not reach the server. Check that the API is running.')
  }

  if (!response.ok) {
    let message = response.statusText || 'Request failed'
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') message = body.detail
    } catch {
      // body was not JSON; keep the status text
    }
    throw new ApiError(response.status, message)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/** Downloads a file (the Excel workbook) with the same sign-in as `apiFetch`. */
export async function apiBlob(path: string): Promise<Blob> {
  const session = supabase ? (await supabase.auth.getSession()).data.session : null
  const headers = new Headers()
  if (session?.access_token) headers.set('Authorization', `Bearer ${session.access_token}`)

  if (!baseUrl) throw new ApiError(0, NOT_CONFIGURED)
  let response: Response
  try {
    response = await fetch(`${baseUrl}${path}`, { headers })
  } catch {
    throw new ApiError(0, 'Could not reach the server. Check that the API is running.')
  }
  if (!response.ok) {
    let message = response.statusText || 'Request failed'
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') message = body.detail
    } catch {
      // body was not JSON; keep the status text
    }
    throw new ApiError(response.status, message)
  }
  return response.blob()
}

export function errorMessage(error: unknown, fallback = 'Something went wrong. Please try again.'): string {
  return error instanceof ApiError ? error.message : fallback
}
