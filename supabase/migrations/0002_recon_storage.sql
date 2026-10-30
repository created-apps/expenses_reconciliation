-- 0002_recon_storage.sql
-- Reconcile: private storage bucket for uploaded files.
--
-- Touches ONLY the bucket row 'recon-files'. No storage policies are created:
-- the backend uses the service role and serves files through short-lived signed URLs.
-- Idempotent: safe to run more than once.
--
-- Run order: 0001, 0002, 0003.

insert into storage.buckets (id, name, public)
values ('recon-files', 'recon-files', false)
on conflict (id) do nothing;

-- ---------------------------------------------------------------------------
-- VERIFICATION
-- ---------------------------------------------------------------------------
--   select id, public from storage.buckets where id = 'recon-files';
--   expect: one row, public = false
--   (If public shows true, the bucket already existed as public: tell the developer,
--    do not leave it public.)

-- ---------------------------------------------------------------------------
-- ROLLBACK (only if asked). Fails if the bucket still contains files; delete those first
-- from the Supabase Storage UI.
-- ---------------------------------------------------------------------------
--   delete from storage.buckets where id = 'recon-files';
