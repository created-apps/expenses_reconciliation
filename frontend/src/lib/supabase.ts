import { createClient, type SupabaseClient } from '@supabase/supabase-js'

// Used ONLY for sign-in / sign-out and to read the session token. The app never queries
// tables from the browser: all data goes through the backend API (lib/api.ts).
const url = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

export const supabase: SupabaseClient | null = url && anonKey ? createClient(url, anonKey) : null

export const SUPABASE_NOT_CONFIGURED =
  'Sign-in is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in frontend/.env.local.'
